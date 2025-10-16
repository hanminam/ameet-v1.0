# src/app/main.py

from datetime import datetime
import os
from pathlib import Path
from fastapi import FastAPI

from app.core.config import settings, logger
from app import db
from app.api.v1 import login, users, setup, discussions as discussions_router, agents
from app.api.v1.admin import (
    agents as admin_agents, 
    discussions as admin_discussions,
    users as admin_users,
    settings as admin_settings
)

from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# ===== [배포 확인용 로그] =====
logger.info("############################################")
logger.info("### AMEET v1.0 - DEPLOYMENT CHECK v2 ###")
logger.info(f"### DEPLOYED AT: {datetime.now()} ###")
logger.info("############################################")
# =================================

app = FastAPI(title=settings.APP_TITLE)

# --- 기본 설정 및 이벤트 핸들러 ---
BASE_DIR = Path(__file__).resolve().parent.parent
app.add_event_handler("startup", db.init_db_connections)
app.add_event_handler("shutdown", db.close_db_connections)

# --- 미들웨어 설정 ---
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 정적 파일 마운트 (worker.js 등을 위함) ---
# BASE_DIR (src 폴더)를 /src 경로에 마운트합니다.
# 이제 /src/app/tools/worker.js 같은 경로로 브라우저에서 파일에 접근할 수 있습니다.
app.mount("/src", StaticFiles(directory=BASE_DIR), name="src")
app.mount("/tools", StaticFiles(directory=BASE_DIR / "app" / "tools"), name="tools")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# --- API 라우터 등록 ---

# v1 사용자용 API
app.include_router(login.router, prefix="/api/v1/login", tags=["login"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(setup.router, prefix="/api/v1/setup", tags=["setup"])
app.include_router(discussions_router.router, prefix="/api/v1/discussions", tags=["Discussions"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["Agents"])

# v1 관리자용 API (여기에 모두 정리)
app.include_router(admin_agents.router, prefix="/api/v1/admin/agents", tags=["Admin: Agents"])
app.include_router(admin_discussions.router, prefix="/api/v1/admin/discussions", tags=["Admin: Discussions"])
app.include_router(admin_users.router, prefix="/api/v1/admin/users", tags=["Admin: Users"])
app.include_router(admin_settings.router, prefix="/api/v1/admin/settings", tags=["Admin: Settings"])

# --- 루트 엔드포인트 ---
@app.get("/", response_class=HTMLResponse)
async def read_root():
    """
    루트 URL로 접속 시, 프론트엔드의 메인 화면인 index.html 파일을 반환합니다.
    """
    return FileResponse(BASE_DIR / "templates/index.html")

# --- 관리자 페이지 엔드포인트 ---
@app.get("/admin", response_class=HTMLResponse)
async def read_admin_page():
    """
    /admin URL 접속 시, 관리자 페이지(admin.html)를 반환합니다.
    참고: 실제 운영 환경에서는 이 엔드포인트에 관리자 인증 로직을 반드시 추가해야 합니다.
    """
    return FileResponse(BASE_DIR / "templates/admin.html")

@app.get("/api/v1/health-check")
async def health_check():
    """Checks the status of Redis and MongoDB connections."""
    redis_status = "error"
    try:
        if db.redis_client:
            await db.redis_client.ping()
            redis_status = "ok"
    except Exception:
        pass

    mongo_status = "error"
    try:
        if db.mongo_client:
            await db.mongo_client.server_info()
            mongo_status = "ok"
    except Exception:
        pass

    return {
        "server_status": "ok",
        "redis_connection": redis_status,
        "mongo_connection": mongo_status,
        "sql_connection": "disabled" # Indicate SQL is no longer used
    }