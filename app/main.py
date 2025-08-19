# app/main.py
from fastapi import FastAPI
from app.core.config import settings, logger

# 설정 객체에서 앱 정보를 가져와 FastAPI 앱을 생성
app = FastAPI(
    title=settings.APP_TITLE,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
)

@app.on_event("startup")
async def startup_event():
    logger.info("Ameet v1.0 application startup.")
    logger.info(f"OpenAI API Key Loaded: {'Yes' if settings.OPENAI_API_KEY != 'your_openai_api_key_here' else 'No'}")


@app.get("/", tags=["Root"])
async def read_root():
    """서버 상태와 로드된 앱 제목을 반환합니다."""
    logger.info("Root endpoint was hit.")
    return {"status": "ok", "app_title": settings.APP_TITLE}