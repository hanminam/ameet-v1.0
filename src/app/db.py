# src/app/db.py

import redis.asyncio as redis
from .core.config import settings, logger

# Redis 클라이언트 변수 선언
redis_client = None

async def init_db_connections():
    """Redis 클라이언트만 초기화하는 함수"""
    global redis_client
    logger.info("Creating Redis client...")
    redis_client = redis.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}", decode_responses=True)
    logger.info("Redis client created.")

async def close_db_connections():
    """Redis 클라이언트만 종료하는 함수"""
    if redis_client:
        await redis_client.close()
    logger.info("Redis connection closed.")