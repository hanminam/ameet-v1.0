from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import user as user_schema
from app.crud.user import get_user_by_email
from app.core import security
import logging

from app.crud import user as user_crud

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/token", response_model=user_schema.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """
    사용자 로그인을 처리하고 액세스 토큰을 반환합니다.
    디버깅 로그가 추가되었습니다.
    """
    logger.info("--- [LOGIN ATTEMPT] ---")
    logger.info(f"[DEBUG] 1. 로그인 시도 이메일: {form_data.username}")

    # users.json 파일에서 사용자 정보를 이메일로 조회합니다.
    user = await get_user_by_email(email=form_data.username)

    if not user:
        logger.warning(f"[DEBUG] 2. 사용자 찾기 실패: '{form_data.username}' 이메일이 users.json에 없습니다.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.info(f"[DEBUG] 2. 사용자 찾기 성공: {user.email}")
    logger.info(f"[DEBUG] 3. 파일에서 읽어온 Hashed Password: {user.hashed_password}")
    
    # 입력된 비밀번호와 파일에 저장된 해시를 비교합니다.
    is_password_valid = security.verify_password(
        form_data.password, user.hashed_password
    )
    
    logger.info(f"[DEBUG] 4. 비밀번호 검증 결과: {is_password_valid}")

    if not is_password_valid:
        logger.warning("[DEBUG] 5. 비밀번호 불일치. 로그인 실패 처리합니다.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.info("[DEBUG] 5. 비밀번호 일치. 토큰을 생성합니다.")

    await user_crud.update_user_last_login(email=user.email)
    logger.info(f"[DEBUG] 6. 사용자 '{user.email}'의 마지막 로그인 시간 업데이트 완료.")
    
    # 인증 성공 시, 액세스 토큰 생성
    access_token = security.create_access_token(
        data={"sub": user.email, "role": user.role}
    )
    
    logger.info("--- [LOGIN SUCCESS] ---")
    return {"access_token": access_token, "token_type": "bearer"}