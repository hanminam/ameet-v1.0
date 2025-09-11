from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from ..core.config import settings

# scrypt의 rounds 값은 n의 로그값이므로, n=16384(2^14)에 해당하는 14로 설정합니다.
# 이것이 모든 환경에서 호환되는 최종 설정입니다.
pwd_context = CryptContext(
    schemes=["scrypt"],
    deprecated="auto",
    scrypt__rounds=14, 
)

# JWT 생성을 위한 설정
ALGORITHM = "HS256"

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=60) # 기본 60분
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """입력된 비밀번호와 해시된 비밀번호를 비교합니다."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """비밀번호를 scrypt 해시로 변환합니다."""
    return pwd_context.hash(password)