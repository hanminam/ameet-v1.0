# src/app/db.py

import redis.asyncio as redis
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.core.config import settings, logger

redis_client = None
mongo_client = None

async def init_db_connections():
    """Initializes connections to Redis and MongoDB."""
    global redis_client, mongo_client

    logger.info("--- [DB-INIT] Initializing database connections (Redis, MongoDB)... ---")

    # --- Redis Initialization ---
    logger.info(f"--- [DB-INIT] Attempting Redis connection to: redis://{settings.REDIS_HOST}:{settings.REDIS_PORT} ---")
    try:
        redis_client = redis.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}", decode_responses=True)
        await redis_client.ping()
        logger.info("--- [DB-INIT] Redis connection successful. ---")
    except Exception as e:
        logger.error(f"--- [DB-INIT-ERROR] Failed during Redis initialization: {e} ---", exc_info=True)
        redis_client = None # Ensure client is None on failure

    # --- MongoDB and Beanie Initialization ---
    try:
        from app.models.discussion import AgentSettings, DiscussionLog, User, SystemSettings

        db_name = settings.MONGO_DB_URL.split("/")[-1].split("?")[0]
        mongo_client = AsyncIOMotorClient(settings.MONGO_DB_URL)
        
        document_models_to_init = [AgentSettings, DiscussionLog, User, SystemSettings]
      
        await init_beanie(
            database=mongo_client[db_name],
            document_models=document_models_to_init
        )
        
        await mongo_client.server_info()
        logger.info(f"--- [DB-INIT] MongoDB & Beanie initialized successfully for DB '{db_name}'. ---")

        # [로그 추가] 초기화 직후 AgentSettings 클래스의 상태를 확인합니다.
        method_exists = hasattr(AgentSettings, 'get_motor_collection')
        logger.info(f"--- [DB-INIT-CHECK] init_beanie 직후, AgentSettings에 get_motor_collection 메서드가 존재하는가? -> {method_exists} ---")
        logger.info(f"--- [DB-INIT-CHECK] init_beanie 시점의 AgentSettings 클래스 ID: {id(AgentSettings)} ---")

    except Exception as e:
        logger.error(f"--- [DB-INIT-ERROR] Failed during MongoDB/Beanie initialization: {e} ---", exc_info=True)
        mongo_client = None # Ensure client is None on failure
        
    logger.info("--- [DB-INIT] All non-SQL DB connections finished. ---")


async def close_db_connections():
    """Closes all active database connections."""
    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed.")
    
    if mongo_client:
        mongo_client.close()
        logger.info("MongoDB connection closed.")