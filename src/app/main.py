# src/app/main.py

from fastapi import FastAPI
from .core.config import settings

# DB 관련 모든 import 제거

app = FastAPI(title=settings.APP_TITLE)

# DB 관련 이벤트 핸들러 모두 제거

@app.get("/")
def read_root():
    return {"message": "AMEET v1.0 API Server is running!"}

@app.get("/api/v1/health-check")
def health_check():
    """오직 서버의 기본 상태만 확인하는 API"""
    return {"status": "ok", "message": "Server is healthy."}