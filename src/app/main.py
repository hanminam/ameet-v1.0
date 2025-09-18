# src/app/main.py

import os
from pathlib import Path
from fastapi import FastAPI

from app.core.config import settings
from app import db
from app.api.v1 import login, users, setup

from sqlalchemy.sql import text
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import discussions as discussions_router
from app.api.v1.admin import agents as admin_agents, discussions as admin_discussions

from app.api.v1.admin import users as admin_users

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

app = FastAPI(title=settings.APP_TITLE)

# --- main.py 파일의 위치를 기준으로 절대 경로 생성 ---
BASE_DIR = Path(__file__).resolve().parent.parent

app.add_event_handler("startup", db.init_db_connections)
app.add_event_handler("shutdown", db.close_db_connections)

app.include_router(login.router, prefix="/api/v1/login", tags=["login"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(setup.router, prefix="/api/v1/setup", tags=["setup"])

# 사용자 토론 관련 API 라우터 등록 (생성, 진행, 조회 모두 포함)
app.include_router(
    discussions_router.router,
    prefix="/api/v1/discussions",
    tags=["Discussions"]
)

# --- 관리자용 API 라우터 등록 ---
app.include_router(
    admin_agents.router, 
    prefix="/api/v1/admin/agents", 
    tags=["Admin: Agents"]
)

# --- 토론 관리 API 라우터 등록 ---
app.include_router(
    admin_discussions.router,
    prefix="/api/v1/admin/discussions",
    tags=["Admin: Discussions"]
)
app.include_router(
    admin_discussions.router,
    prefix="/api/v1/admin/discussions",
    tags=["Admin: Discussions"]
)

# --- 관리자용 API 라우터 등록 ---
app.include_router(
    admin_agents.router, 
    prefix="/api/v1/admin/agents", 
    tags=["Admin: Agents"]
)

# --- 관리자용 사용자 관리 API 라우터 ---
app.include_router(
    admin_users.router,
    prefix="/api/v1/admin/users",
    tags=["Admin: Users"]
)

# 이 미들웨어는 Cloud Run과 같은 프록시 환경에서 
# X-Forwarded-Proto, X-Forwarded-For 등의 헤더를 신뢰하도록 하여
# 애플리케이션이 실제 요청 프로토콜(https)을 인지하게 해줍니다.
# CORS 미들웨어보다 앞에 추가하는 것이 좋습니다.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# --- CORS 미들웨어 추가 ---
# 모든 출처(origins)에서의 요청을 허용합니다. (개발 및 테스트용)
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- CORS 설정 끝 ---

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