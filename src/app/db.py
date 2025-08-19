# src/app/db.py

import os
import redis.asyncio as redis
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# [신규] Cloud SQL Python Connector 임포트
from google.cloud.sql.connector import Connector

from .core.config import settings, logger
from .models.base import Base
from .models.user import User
from .models.discussion import DiscussionLog, AgentSettings

# [전면 수정] 환경에 따라 올바른 SQLAlchemy 엔진을 생성하는 함수
async def get_engine():
    """환경에 따라 올바른 비동기 SQLAlchemy 엔진을 생성하여 반환합니다."""
    # Cloud Run 환경인지 확인
    if settings.INSTANCE_CONNECTION_NAME:
        logger.info("Cloud Run environment detected. Using async Cloud SQL Connector.")
        
        # Connector 객체를 초기화 (컨텍스트 매니저 외부에서)
        connector = Connector()

        # 비동기 연결 생성 함수
        async def get_conn():
            # aiomysql를 직접 사용하여 비동기 연결 생성
            conn = await connector.connect_async(
                settings.INSTANCE_CONNECTION_NAME,
                "aiomysql",
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                db=settings.DB_NAME,
            )
            # aiomysql의 연결 객체를 반환
            return conn

        # 비동기 엔진 생성
        engine = create_async_engine(
            "mysql+aiomysql://",
            creator=get_conn,
            echo=False,
            future=True
        )
        return engine
    else:
        logger.info("Local environment detected. Using Public IP.")
        # 로컬 환경에서는 기존의 공개 IP 주소 방식을 사용
        db_url = (
            f"mysql+aiomysql://{settings.DB_USER}:{settings.DB_PASSWORD}"
            f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
        )
        engine = create_async_engine(db_url, echo=True, future=True)
        return engine

# --- 애플리케이션의 다른 부분에서 사용할 변수들 ---
# (주의: engine 객체는 이제 비동기 함수를 통해 초기화되어야 합니다)
engine = None
AsyncDBSession = None

redis_client = redis.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}", decode_responses=True)
mongo_client = AsyncIOMotorClient(settings.MONGO_DB_URL)

async def init_db_connections():
    global engine, AsyncDBSession
    logger.info("Initializing database connections...")
    
    # [수정] get_engine() 비동기 함수를 호출하여 엔진을 가져옵니다.
    engine = await get_engine()
    AsyncDBSession = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    await init_beanie(
        database=mongo_client.ameet_db,
        document_models=[DiscussionLog, AgentSettings]
    )
    logger.info("MongoDB connection and Beanie initialized.")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("MariaDB tables checked/created.")

async def close_db_connections():
    logger.info("Closing database connections...")
    mongo_client.close()
    await redis_client.close()
    if engine:
        await engine.dispose()
    logger.info("Database connections closed.")