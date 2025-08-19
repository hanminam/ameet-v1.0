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
        await redis_client.ping()
        redis_status = "ok"
    except Exception as e:
        redis_status = f"error: {e}"

    return {
        "server_status": "ok",
        "redis_connection": redis_status
    }