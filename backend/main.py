"""
观测站后端。

启动方式:
    cd backend
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

打开 http://localhost:8000 即可看到前端页面。
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.background import BackgroundScheduler

import fetcher

app = FastAPI(title="观测站 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

scheduler = BackgroundScheduler(timezone="UTC")

# 静态不属于"实时数据源"的板块,前端用它来做"没有动态"的分区展示,
# 不需要抓取任务,只需要一句诚实的说明。
STATIC_TOPICS = [
    {"id": "bazi", "label": "八字紫薇状况", "reason": "命理规则体系恒定,不存在按小时更新的新进展"},
    {"id": "acim", "label": "奇迹课程相关组织", "reason": "长周期灵修社群活动,无专门媒体做小时级追踪"},
    {"id": "mind", "label": "思想灵修 / 心神表达", "reason": "持续性思想实践内容,不是事件性新闻"},
    {"id": "body", "label": "体态姿态与内脏修复", "reason": "方法论更新以年计,不存在今日快讯"},
    {"id": "heal", "label": "情感疗愈日报", "reason": "没有专门做每日疗愈快讯的一手媒体源"},
    {"id": "ququ", "label": "曲曲大女人", "reason": "未检索到可识别的公开信息源,需你提供更具体名称"},
    {"id": "human3", "label": "human3.0", "reason": "多个项目共用的泛化概念,无统一新闻源"},
    {"id": "megacity", "label": "全球超大城市对比", "reason": "统计类研究,更新周期以季度/年计"},
    {"id": "xianyu", "label": "闲鱼市场情况", "reason": "官方不披露小时级数据,自媒体解读可信度低"},
    {"id": "embed", "label": "嵌入式行业", "reason": "发布分散在各厂商官网,需指定具体厂商才能精准追踪"},
    {"id": "sysjob", "label": "系统工程师职业", "reason": "薪资/招聘趋势通常是季度或半年报告"},
    {"id": "media", "label": "自媒体行业", "reason": "趋势观察类内容,无统一小时级数据源"},
    {"id": "internet", "label": "互联网大厂动态", "reason": "需指定具体公司才能精准抓取,泛主题无法验证"},
]


@app.on_event("startup")
def on_startup():
    fetcher.init_db()
    # 先立刻跑一次,不用等第一个调度周期
    fetcher.run_all_fetchers()
    scheduler.add_job(fetcher.fetch_crypto, "interval", minutes=5, id="fetch_crypto")
    scheduler.add_job(fetcher.fetch_rss, "interval", minutes=60, id="fetch_rss")
    scheduler.start()


@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown()


@app.get("/api/feed")
def get_feed(topic: str = Query(default=None), limit: int = Query(default=30)):
    conn = fetcher.get_conn()
    if topic:
        rows = conn.execute(
            "SELECT * FROM items WHERE topic = ? ORDER BY fetched_at DESC LIMIT ?",
            (topic, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM items ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/status")
def get_status():
    conn = fetcher.get_conn()
    rows = conn.execute("SELECT * FROM sources").fetchall()
    conn.close()
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "sources": [dict(r) for r in rows],
    }


@app.get("/api/static-topics")
def get_static_topics():
    return STATIC_TOPICS


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")
