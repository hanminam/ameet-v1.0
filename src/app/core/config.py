# app/core/config.py

import logging
from pydantic import computed_field
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

    GOOGLE_API_KEY="AIzaSyDdu2rCchEJEQpT2b46MrnkcWXvul8a3T8"
    OPENAI_API_KEY="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"
    ANTHROPIC_API_KEY="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"
    PERPLEXITY_API_KEY="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"
    TAVILY_API_KEY="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"

    DB_USER: str = "ameet_user"
    DB_PASSWORD: str = "Kimnc0624!@"
    DB_NAME: str = "ameet_db"
    DB_HOST: str = "34.64.212.12"
    DB_PORT: str = "3306"

    REDIS_HOST: str = "10.48.219.179"
    REDIS_PORT: int = 6379

    MONGO_DB_URL: str = "mongodb+srv://root:Kimnc0624!%40@cluster0.6ckqorp.mongodb.net/ameet_db?retryWrites=true&w=majority"

    # [추가] SQLAlchemy가 사용할 완전한 데이터베이스 접속 URL 생성
    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

# 설정 객체 생성
settings = Settings()

# 기본 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

logger.info("Configuration loaded successfully.")
logger.info(f"Application Title: {settings.APP_TITLE}")