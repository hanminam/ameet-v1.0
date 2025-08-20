# src/app/db.py

import redis.asyncio as redis

from motor.motor_asyncio import AsyncIOMotorClient

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError
from google.cloud.sql.connector import Connector

from .core.config import settings, logger
from .models.base import Base
from .models.user import User

redis_client = None
mongo_client = None
engine = None
AsyncDBSession = None

async def init_db_connections():
    global redis_client, mongo_client, engine, AsyncDBSession

    logger.info("--- [DB-INIT-STEP-1] `init_db_connections` function started. ---")

    # --- Redis 초기화 ---
    try:
        redis_client = redis.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}", decode_responses=True)
        await redis_client.ping()

    except Exception as e:
        logger.error(f"--- [DB-INIT-ERROR] Failed during Redis initialization: {e} ---", exc_info=True)
        return

    # --- MongoDB 초기화 ---
    try:
        logger.info("--- [DB-INIT-STEP-5] Attempting to create MongoDB client... ---")
        mongo_client = AsyncIOMotorClient(settings.MONGO_DB_URL)
        # MongoDB는 연결 테스트를 위해 서버 정보를 가져옵니다.
        await mongo_client.server_info()
        logger.info("--- [DB-INIT-STEP-6] MongoDB client connection successful. ---")

    except Exception as e:
        logger.error(f"--- [DB-INIT-ERROR] Failed during MongoDB initialization: {e} ---", exc_info=True)
        return

    logger.info("--- [DB-INIT-STEP-7] All DB connections finished. ---")

    # --- [신규] MariaDB/MySQL 초기화 ---
    try:
        # --- 1단계: 엔진 생성 ---
        logger.info("--- [DB-INIT-STEP-SQL-1] Attempting to create SQL engine... ---")
        
        # [수정] 'coroutine' 오류를 해결했던 Unix 소켓 URL 방식으로 되돌립니다.
        if settings.INSTANCE_CONNECTION_NAME:
            logger.info("Cloud Run environment detected. Using Unix Socket.")
            engine = create_async_engine(
                f"mysql+aiomysql://{settings.DB_USER}:{settings.DB_PASSWORD}@"
                f"/{settings.DB_NAME}?unix_socket=/cloudsql/{settings.INSTANCE_CONNECTION_NAME}"
            )
        else: # 로컬 환경
            logger.info("Local environment detected. Using Public IP.")
            db_url = (
                f"mysql+aiomysql://{settings.DB_USER}:{settings.DB_PASSWORD}"
                f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
            )
            engine = create_async_engine(db_url)
        
        logger.info("--- [DB-INIT-STEP-SQL-2] SQL engine created successfully. ---")
        
        # --- 2단계: 테이블 생성 (오류 처리 강화) ---
        # [수정] 'Table already exists' 오류를 처리하는 로직을 적용합니다.
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("--- [DB-INIT-STEP-SQL-3] SQL tables checked/created. ---")
        except OperationalError as e:
            logger.warning(f"--- [DB-INIT-WARN] Harmless error during table creation (already exists?): {e} ---")

        # --- 3단계: 세션 생성 ---
        AsyncDBSession = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        logger.info("--- [DB-INIT-STEP-SQL-4] SQL SessionMaker created. ---")

    except Exception as e:
        logger.error(f"--- [DB-INIT-ERROR] Failed during SQL initialization: {e} ---", exc_info=True)
        return
        
    logger.info("--- [DB-INIT-STEP-7] All DB connections finished. ---")

async def close_db_connections():
    if redis_client:
        await redis_client.close()
    
    if mongo_client:
        mongo_client.close()

    if engine:
        await engine.dispose()
        
    logger.info("All DB connections closed.")