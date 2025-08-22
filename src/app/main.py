# src/app/main.py

import os
from fastapi import FastAPI
from .core.config import settings
from . import db
from sqlalchemy.sql import text
from .api.v1 import login, users, setup
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title=settings.APP_TITLE)

app.add_event_handler("startup", db.init_db_connections)
app.add_event_handler("shutdown", db.close_db_connections)

app.include_router(login.router, prefix="/api/v1/login", tags=["login"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(setup.router, prefix="/api/v1/setup", tags=["setup"])

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
    try:
        # main.py 파일의 현재 위치를 기준으로 절대 경로를 계산합니다.
        # os.path.abspath(__file__) -> 현재 파일(main.py)의 절대 경로
        # os.path.dirname(...)      -> 해당 파일이 속한 디렉토리 (src/app)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # src/app에서 한 단계 위(src)로 올라가 templates/index.html 경로를 조합합니다.
        file_path = os.path.join(current_dir, "..", "templates", "index.html")
        
        # 계산된 경로가 실제로 존재하는지 확인합니다.
        if not os.path.exists(file_path):
            # 파일이 없다면, 계산된 전체 경로를 포함한 에러 메시지를 반환합니다.
            return HTMLResponse(content=f"<h1>File Not Found</h1><p>Server tried to find file at: {file_path}</p>", status_code=404)
            
        return FileResponse(file_path)
    except Exception as e:
        return HTMLResponse(content=f"<h1>An error occurred</h1><p>{e}</p>", status_code=500)
# --- 루트 엔드포인트 수정 끝 ---

@app.get("/api/v1/health-check")
async def health_check():
    # Redis 상태 확인
    redis_status = "error"
    try:
        await db.redis_client.ping()
        redis_status = "ok"
    except Exception:
        pass

    # MongoDB 상태 확인
    mongo_status = "error"
    try:
        await db.mongo_client.server_info()
        mongo_status = "ok"
    except Exception:
        pass

    # [신규] MySQL 상태 확인
    sql_status = "error"
    try:
        if db.AsyncDBSession:
            async with db.AsyncDBSession() as session:
                # 간단한 쿼리를 실행하여 연결 테스트
                await session.execute(text("SELECT 1"))
            sql_status = "ok"
        else:
            sql_status = "not initialized"
    except Exception:
        pass

    return {
        "server_status": "ok",
        "redis_connection": redis_status,
        "mongo_connection": mongo_status,
        "sql_connection": sql_status
    }