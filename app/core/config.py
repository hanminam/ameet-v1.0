# app/core/config.py

import logging
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # .env 파일을 읽도록 다시 설정합니다.
    # 이 설정이 있어도, 시스템(Cloud Run)에 동일한 이름의 환경 변수가 있으면
    # 시스템의 값을 항상 우선적으로 사용합니다.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra='ignore')

    # .env 파일에 정의된 변수들을 타입과 함께 선언
    APP_TITLE: str = "AMEET v1.0"
    APP_DESCRIPTION: str = "AI 집단지성 토론 플랫폼"
    APP_VERSION: str = "1.0.0"

    OPENAI_API_KEY: str = "default_key"
    GOOGLE_API_KEY: str = "default_key"
    ANTHROPIC_API_KEY: str = "default_key"

# 설정 객체 생성
settings = Settings()

# 기본 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

logger.info("Configuration loaded successfully.")
logger.info(f"Application Title: {settings.APP_TITLE}")