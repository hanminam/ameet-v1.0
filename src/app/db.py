# src/app/db.py

import redis.asyncio as redis
from .core.config import settings, logger # logger를 import하는지 확인

redis_client = None

# MongoDB, MariaDB 관련 import 및 변수 선언은 그대로 둡니다.
mongo_client = None
engine = None
AsyncDBSession = None

async def init_db_connections():
    global redis_client, mongo_client, engine, AsyncDBSession

    # --- [로그 추가] ---
    logger.info("--- [DB-INIT-STEP-1] `init_db_connections` function started. ---")

    try:
        # --- [로그 추가] ---
        logger.info("--- [DB-INIT-STEP-2] Attempting to create Redis client... ---")
        
        redis_client = redis.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}", 
            decode_responses=True
        )
        
        # --- [로그 추가] ---
        logger.info("--- [DB-INIT-STEP-3] Redis client object created successfully. ---")
        
        # Redis PING 테스트를 여기서 바로 해볼 수 있습니다.
        await redis_client.ping()
        logger.info("--- [DB-INIT-STEP-4] Redis PING test successful. ---")

    except Exception as e:
        # --- [로그 추가] ---
        # 오류가 발생하면 로그에 상세히 기록합니다.
        logger.error(f"--- [DB-INIT-ERROR] Failed during Redis initialization: {e} ---", exc_info=True)
        # 오류 발생 시, redis_client가 None으로 유지될 수 있습니다.
        redis_client = None # 확실히 None으로 설정
        # 일단 Redis에서 실패하면 더 진행하지 않고 함수를 종료할 수 있습니다.
        return 

    # MongoDB 및 MariaDB 초기화 로직은 그대로 둡니다 (향후 테스트를 위해).
    # ...

    logger.info("--- [DB-INIT-STEP-5] `init_db_connections` function finished. ---")


async def close_db_connections():
    if redis_client:
        await redis_client.close()
    logger.info("Redis connection closed.")
    # ... (나머지 종료 로직)