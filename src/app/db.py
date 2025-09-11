# src/app/db.py

import redis.asyncio as redis
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.core.config import settings, logger
from app.models.discussion import DiscussionLog, AgentSettings

redis_client = None
mongo_client = None

async def init_db_connections():
    """Initializes connections to Redis and MongoDB."""
    global redis_client, mongo_client

    logger.info("--- [DB-INIT] Initializing database connections (Redis, MongoDB)... ---")

    # --- Redis Initialization ---
    try:
        redis_client = redis.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}", decode_responses=True)
        await redis_client.ping()
        logger.info("--- [DB-INIT] Redis connection successful. ---")
    except Exception as e:
        logger.error(f"--- [DB-INIT-ERROR] Failed during Redis initialization: {e} ---", exc_info=True)
        redis_client = None # Ensure client is None on failure

    # --- MongoDB and Beanie Initialization ---
    try:
        db_name = settings.MONGO_DB_URL.split("/")[-1].split("?")[0]
        mongo_client = AsyncIOMotorClient(settings.MONGO_DB_URL)
        
        await init_beanie(
            database=mongo_client[db_name],
            document_models=[AgentSettings, DiscussionLog]
        )
        
        await mongo_client.server_info()
        logger.info(f"--- [DB-INIT] MongoDB & Beanie initialized successfully for DB '{db_name}'. ---")
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