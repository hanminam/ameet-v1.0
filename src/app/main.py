# src/app/main.py

from fastapi import FastAPI
from .core.config import settings

# --- [핵심 수정 1] ---
# 변수를 직접 가져오는 대신, 'db' 모듈 전체를 가져옵니다.
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
    redis_status = "not connected"
    try:
        # 복사된 변수가 아닌, db 모듈을 통해 최신 redis_client에 접근합니다.
        await db.redis_client.ping()
        redis_status = "ok"
    except Exception as e:
        redis_status = f"error: {e}"

    return {
        "server_status": "ok",
        "redis_connection": redis_status
    }