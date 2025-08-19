# src/app/main.py

from fastapi import FastAPI
from .core.config import settings
from . import db

app = FastAPI(title=settings.APP_TITLE)

# 이벤트 핸들러는 db 모듈의 함수를 그대로 사용합니다.
app.add_event_handler("startup", db.init_db_connections)
app.add_event_handler("shutdown", db.close_db_connections)

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
        pass # 오류 로그는 db.py에서 이미 남김

    # [신규] MongoDB 상태 확인
    mongo_status = "error"
    try:
        await db.mongo_client.server_info()
        mongo_status = "ok"
    except Exception:
        pass # 오류 로그는 db.py에서 이미 남김

    return {
        "server_status": "ok",
        "redis_connection": redis_status,
        "mongo_connection": mongo_status
    }