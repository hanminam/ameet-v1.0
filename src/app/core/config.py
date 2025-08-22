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

    OPENAI_API_KEY: str = "default_key"
    GOOGLE_API_KEY: str = "default_key"
    ANTHROPIC_API_KEY: str = "default_key"

    DB_USER: str = "ameet_user"
    DB_PASSWORD: str = "Kimnc0624!"
    DB_NAME: str = "ameet_db"
    DB_HOST: str = "34.64.212.12"
    DB_PORT: str = "3306"

    # [수정] Cloud Run 환경에서 주입되는 인스턴스 연결 이름
    # 로컬에서는 이 값이 없으므로 None이 됩니다.
    INSTANCE_CONNECTION_NAME: str | None = None

    # Cloud Run 환경의 Memorystore Redis IP
    CLOUD_REDIS_HOST: str = "10.48.219.179"
    # 로컬 개발 환경의 Redis IP (Docker 또는 로컬 설치)
    LOCAL_REDIS_HOST: str = "127.0.0.1" # 또는 "localhost"
    REDIS_PORT: int = 6379

    MONGO_DB_URL: str = "mongodb+srv://root:Kimnc0624!%40@cluster0.6ckqorp.mongodb.net/ameet_db?retryWrites=true&w=majority"

    # [신규] JWT 서명을 위한 시크릿 키 (실제 운영 시에는 .env에서 관리)
    SECRET_KEY: str = "a_very_secret_key_that_should_be_changed"

    # --- [수정] 환경에 따라 Redis 호스트를 동적으로 결정 ---
    @computed_field
    @property
    def REDIS_HOST(self) -> str:
        # INSTANCE_CONNECTION_NAME은 Cloud Run 환경에만 존재합니다.
        # 이 변수가 없으면 로컬 환경으로 간주합니다.
        if self.INSTANCE_CONNECTION_NAME:
            print("--- [Config] Cloud Run 환경 감지. Cloud Redis를 사용합니다. ---")
            return self.CLOUD_REDIS_HOST
        else:
            print("--- [Config] 로컬 환경 감지. Local Redis를 사용합니다. ---")
            return self.LOCAL_REDIS_HOST
    # --- Redis 설정 수정 끝 ---

    # [추가] SQLAlchemy가 사용할 완전한 데이터베이스 접속 URL 생성
    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        # Cloud Run 환경일 경우 (INSTANCE_CONNECTION_NAME이 설정됨)
        if self.INSTANCE_CONNECTION_NAME:
            # Unix Socket을 사용하는 내부 주소 형식을 사용합니다.
            return (
                f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASSWORD}@"
                f"/{self.DB_NAME}?unix_socket=/cloudsql/{self.INSTANCE_CONNECTION_NAME}"
            )
        # 로컬 환경일 경우 (INSTANCE_CONNECTION_NAME이 없음)
        else:
            # 기존의 공개 IP 주소 형식을 사용합니다.
            return (
                f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASSWORD}"
                f"@{self.DB_HOST}:3306/{self.DB_NAME}"
            )

# 설정 객체 생성
settings = Settings()

# 기본 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

logger.info("Configuration loaded successfully.")
logger.info(f"Application Title: {settings.APP_TITLE}")