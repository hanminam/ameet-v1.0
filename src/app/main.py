# app/main.py
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from .core.config import settings, logger
from .db import init_db_connections, close_db_connections, AsyncDBSession, redis_client, mongo_client

# 설정 객체에서 앱 정보를 가져와 FastAPI 앱을 생성
app = FastAPI(
    title=settings.APP_TITLE,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
)

@app.on_event("startup")
async def startup_event():
    logger.info("Ameet v1.0 application startup.")
    await init_db_connections()

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Ameet v1.0 application shutdown.")
    await close_db_connections()

# [단위 테스트용] DB 연결 상태 확인 엔드포인트
@app.get("/api/v1/health-check", tags=["System"])
async def health_check(db_session: AsyncSession = Depends(AsyncDBSession)):
    results = {}
    # 1. MariaDB 연결 확인
    try:
        await db_session.execute(text("SELECT 1"))
        results["mariadb"] = "ok"
    except Exception as e:
        logger.error(f"MariaDB connection failed: {e}")
        results["mariadb"] = "failed"

    # 2. Redis 연결 확인
    try:
        await redis_client.ping()
        results["redis"] = "ok"
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        results["redis"] = "failed"
    
    # 3. MongoDB 연결 확인
    try:
        await mongo_client.admin.command('ping')
        results["mongodb"] = "ok"
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        results["mongodb"] = "failed"

    return results