# src/app/db.py

import redis.asyncio as redis

from motor.motor_asyncio import AsyncIOMotorClient

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
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
        logger.info("--- [DB-INIT-STEP-SQL-1] Attempting to create SQL engine... ---")
        
        # Cloud Run 환경인지 확인
        if settings.INSTANCE_CONNECTION_NAME:
            logger.info("Cloud Run environment detected. Using async Cloud SQL Connector.")
            connector = Connector()
            
            # 연결 함수 정의
            def get_conn():
                # [수정] 드라이버 이름을 'aiomysql'로 변경
                conn = connector.connect(
                    settings.INSTANCE_CONNECTION_NAME,
                    "aiomysql", 
                    user=settings.DB_USER,
                    password=settings.DB_PASSWORD,
                    db=settings.DB_NAME,
                )
                return conn

            # [수정] SQLAlchemy 엔진 URL의 드라이버 부분도 'aiomysql'로 변경
            engine = create_async_engine(
                "mysql+aiomysql://",
                creator=get_conn,
            )
        else: # 로컬 환경
            logger.info("Local environment detected. Using Public IP.")
            # [수정] 로컬 DB URL의 드라이버 부분도 'aiomysql'로 변경
            db_url = (
                f"mysql+aiomysql://{settings.DB_USER}:{settings.DB_PASSWORD}"
                f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
            )
            engine = create_async_engine(db_url)
        
        logger.info("--- [DB-INIT-STEP-SQL-2] SQL engine created successfully. ---")
        
        # 테이블 생성
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("--- [DB-INIT-STEP-SQL-3] SQL tables checked/created. ---")
        
        # 세션메이커 생성
        AsyncDBSession = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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