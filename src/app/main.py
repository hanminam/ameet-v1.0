# src/app/main.py

from fastapi import FastAPI
from .core.config import settings
from . import db
from sqlalchemy.sql import text
from .api.v1 import login, users, setup

app = FastAPI(title=settings.APP_TITLE)

app.add_event_handler("startup", db.init_db_connections)
app.add_event_handler("shutdown", db.close_db_connections)

# API 라우터 포함
app.include_router(login.router, prefix="/api/v1/login", tags=["login"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(setup.router, prefix="/api/v1/setup", tags=["setup"])

@app.get("/")
def read_root():
    return {"message": "AMEET v1.0 API Server is running!"}

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