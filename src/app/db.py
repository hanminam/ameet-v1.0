# app/db.py

import redis.asyncio as redis

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from .core.config import settings, logger
from .models.base import Base # Base를 새로 만든 base.py에서 가져옵니다.
from .models.user import User # User 모델을 직접 임포트합니다.
from .models.discussion import DiscussionLog, AgentSettings

# SQLAlchemy (MariaDB) 설정
engine = create_async_engine(settings.DATABASE_URL, echo=True, future=True)
AsyncDBSession = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Redis 설정
redis_client = redis.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}", decode_responses=True)

# MongoDB (beanie) 설정
mongo_client = AsyncIOMotorClient(settings.MONGO_DB_URL)

async def init_db_connections():
    """애플리케이션 시작 시 DB 연결을 초기화합니다."""
    logger.info("Initializing database connections...")
    
    # MongoDB 연결 및 Beanie 초기화
    await init_beanie(
        database=mongo_client.ameet_db,
        document_models=[DiscussionLog, AgentSettings]
    )
    logger.info("MongoDB connection and Beanie initialized.")

    # MariaDB 테이블 생성 (테이블이 없을 경우)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("MariaDB tables checked/created.")

async def close_db_connections():
    """애플리케이션 종료 시 DB 연결을 닫습니다."""
    logger.info("Closing database connections...")
    mongo_client.close()
    await redis_client.close()
    await engine.dispose()
    logger.info("Database connections closed.")