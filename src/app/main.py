from fastapi import FastAPI
from .core.config import settings
from .db import init_db_connections, close_db_connections, redis_client

app = FastAPI(title=settings.APP_TITLE)

app.add_event_handler("startup", init_db_connections)
app.add_event_handler("shutdown", close_db_connections)

@app.get("/")
def read_root():
    return {"message": "AMEET v1.0 API Server is running!"}

@app.get("/api/v1/health-check")
async def health_check(): # async로 변경
    """서버 및 Redis 연결 상태를 확인"""
    redis_status = "not connected"
    try:
        # 이 시점에는 startup 이벤트가 실행되어 redis_client가 채워져 있어야 합니다.
        await redis_client.ping()
        redis_status = "ok"
    except Exception as e:
        # redis_client가 None이면 여기서 'NoneType' 오류가 발생합니다.
        redis_status = f"error: {e}"

    return {
        "server_status": "ok",
        "redis_connection": redis_status
    }