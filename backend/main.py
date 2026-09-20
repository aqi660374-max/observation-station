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

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.background import BackgroundScheduler

import fetcher
from content import CONTENT_TREE

app = FastAPI(title="观测站 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

scheduler = BackgroundScheduler(timezone="UTC")

# 静态知识树内容维护在 content.py 里,方便以后单独扩充某个板块
# 而不用改动这个文件。


@app.on_event("startup")
def on_startup():
    fetcher.init_db()
    fetcher.seed_profile_defaults()
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


@app.get("/api/profile")
def get_profile_api():
    return fetcher.get_profile()


@app.post("/api/profile")
async def save_profile_api(request: Request):
    body = await request.json()
    section_id = body.get("id")
    content = body.get("content", "")
    if not section_id:
        return {"ok": False, "error": "missing id"}
    fetcher.set_profile_section(section_id, content)
    return {"ok": True}


@app.post("/api/profile/clear")
def clear_profile_api():
    fetcher.clear_profile()
    return {"ok": True}


@app.get("/api/tree")
def get_tree():
    return CONTENT_TREE


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")
