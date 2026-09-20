"""
数据抓取模块。
每个 fetch_* 函数负责一个数据源:抓取 -> 清洗 -> 写入 SQLite。
所有函数遵循同一个约定:成功抓到几条,就 insert 几条,并更新 sources 表的 last_success_at。
"""

import sqlite3
import time
import requests
import feedparser
from datetime import datetime, timezone

import os

DB_PATH = os.environ.get("OBSERVATION_DB_PATH", "observation.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT,
            source_name TEXT,
            source_url TEXT,
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            is_live_source INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sources (
            name TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            cadence_minutes INTEGER NOT NULL,
            last_success_at TEXT,
            last_error TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS profile (
            section_id TEXT PRIMARY KEY,
            content TEXT NOT NULL DEFAULT '',
            updated_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# "我是谁" 自我画像板块:完全由用户自己写、自己改,不预设内容。
# ---------------------------------------------------------------------------
PROFILE_SECTIONS = [
    {"id": "purpose", "label": "我为了什么而前进"},
    {"id": "identity", "label": "我是谁"},
    {"id": "discipline", "label": "我的纪律"},
    {"id": "order", "label": "我的秩序"},
    {"id": "focus", "label": "我的焦点"},
    {"id": "social_boundary", "label": "社交边界与渴望"},
    {"id": "time_boundary", "label": "时间边界的必要性"},
    {"id": "aesthetic_preference", "label": "审美与情感偏好"},
    {"id": "money_power", "label": "对钱权的追逐"},
    {"id": "integration", "label": "整合思考(跨领域串联)"},
]


def seed_profile_defaults():
    """只在对应字段完全没有内容时才写入种子文本,不会覆盖你已经改过的内容。"""
    seeds = {
        "aesthetic_preference": "你提到过对长发男生的偏爱——这条先记在这里,具体想展开成什么样的自我理解,由你自己继续写。",
        "money_power": "你提到过对钱和权力的追逐——这条先记在这里,具体是想成为什么样的关系(工具/目标/边界在哪),由你自己继续写。",
    }
    conn = get_conn()
    for section_id, text in seeds.items():
        existing = conn.execute(
            "SELECT content FROM profile WHERE section_id = ?", (section_id,)
        ).fetchone()
        if existing is None:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO profile (section_id, content, updated_at) VALUES (?, ?, ?)",
                (section_id, text, now),
            )
    conn.commit()
    conn.close()


def get_profile():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM profile").fetchall()
    conn.close()
    saved = {r["section_id"]: dict(r) for r in rows}
    result = []
    for sec in PROFILE_SECTIONS:
        saved_row = saved.get(sec["id"])
        result.append({
            "id": sec["id"],
            "label": sec["label"],
            "content": saved_row["content"] if saved_row else "",
            "updated_at": saved_row["updated_at"] if saved_row else None,
        })
    return result


def set_profile_section(section_id, content):
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO profile (section_id, content, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(section_id) DO UPDATE SET
            content = excluded.content,
            updated_at = excluded.updated_at
        """,
        (section_id, content, now),
    )
    conn.commit()
    conn.close()


def clear_profile():
    """清空所有"我是谁"字段的内容(不删表结构,只清空数据)。"""
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    for sec in PROFILE_SECTIONS:
        conn.execute(
            """
            INSERT INTO profile (section_id, content, updated_at)
            VALUES (?, '', ?)
            ON CONFLICT(section_id) DO UPDATE SET
                content = '',
                updated_at = excluded.updated_at
            """,
            (sec["id"], now),
        )
    conn.commit()
    conn.close()


def _mark_source(name, topic, cadence_minutes, error=None):
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO sources (name, topic, cadence_minutes, last_success_at, last_error)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            last_success_at = excluded.last_success_at,
            last_error = excluded.last_error
        """,
        (name, topic, cadence_minutes, None if error else now, error),
    )
    conn.commit()
    conn.close()


def _insert_item(topic, title, summary, source_name, source_url, published_at, is_live_source=1):
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    # 用 title+topic 做简单去重:同一条新闻/同一分钟的价格快照不用重复插入
    existing = conn.execute(
        "SELECT id FROM items WHERE topic = ? AND title = ? ORDER BY id DESC LIMIT 1",
        (topic, title),
    ).fetchone()
    if existing:
        conn.close()
        return
    conn.execute(
        """
        INSERT INTO items (topic, title, summary, source_name, source_url, published_at, fetched_at, is_live_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (topic, title, summary, source_name, source_url, published_at, now, is_live_source),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 数据源 1:CoinGecko 价格快照(真正的分钟级实时数据)
# ---------------------------------------------------------------------------
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_PARAMS = {
    "ids": "bitcoin,ethereum,solana",
    "vs_currencies": "usd",
    "include_24hr_change": "true",
}


def fetch_crypto():
    try:
        resp = requests.get(COINGECKO_URL, params=COINGECKO_PARAMS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print(f"[fetch_crypto] CoinGecko 原始响应: {data}")
        now = datetime.now(timezone.utc).isoformat()
        name_map = {"bitcoin": "比特币", "ethereum": "以太坊", "solana": "Solana"}
        inserted = 0
        for coin_id, info in data.items():
            price = info.get("usd")
            change = info.get("usd_24h_change")
            if price is None:
                print(f"[fetch_crypto] 跳过 {coin_id}: 没有 usd 字段, info={info}")
                continue
            title = f"{name_map.get(coin_id, coin_id)} 快照 {now[:16]}"
            change_str = f"{change:+.2f}%" if change is not None else "N/A"
            summary = f"{name_map.get(coin_id, coin_id)} 报 ${price:,.2f},24小时涨跌 {change_str}"
            _insert_item(
                topic="crypto",
                title=title,
                summary=summary,
                source_name="CoinGecko API",
                source_url="https://www.coingecko.com/",
                published_at=now,
                is_live_source=1,
            )
            inserted += 1
        if inserted == 0:
            raise RuntimeError(f"请求成功但没有任何一条数据插入,原始响应: {data}")
        print(f"[fetch_crypto] 本次插入 {inserted} 条")
        _mark_source("coingecko", "crypto", cadence_minutes=5)
        return True
    except Exception as e:
        print(f"[fetch_crypto] 出错: {e}")
        _mark_source("coingecko", "crypto", cadence_minutes=5, error=str(e))
        return False


# ---------------------------------------------------------------------------
# 数据源 2:RSS 聚合示例(The Block —— 更新频率不固定,按小时轮询即可)
# 换成任何你想追踪的 RSS 源都行,把 url 换掉、topic 换成对应板块即可。
# ---------------------------------------------------------------------------
RSS_SOURCES = [
    {"topic": "crypto", "name": "The Block", "url": "https://www.theblock.co/rss.xml"},
]


def fetch_rss():
    for src in RSS_SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            if feed.bozo and not feed.entries:
                raise RuntimeError(f"解析失败: {feed.bozo_exception}")
            for entry in feed.entries[:10]:
                published = getattr(entry, "published", None) or datetime.now(timezone.utc).isoformat()
                _insert_item(
                    topic=src["topic"],
                    title=entry.title,
                    summary=getattr(entry, "summary", "")[:200],
                    source_name=src["name"],
                    source_url=entry.link,
                    published_at=published,
                    is_live_source=1,
                )
            _mark_source(src["name"], src["topic"], cadence_minutes=60)
        except Exception as e:
            _mark_source(src["name"], src["topic"], cadence_minutes=60, error=str(e))


def run_all_fetchers():
    fetch_crypto()
    fetch_rss()


if __name__ == "__main__":
    init_db()
    run_all_fetchers()
    print("抓取完成,检查 observation.db")
