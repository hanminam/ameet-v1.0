# src/app/api/v1/setup.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.schemas import user as user_schema
from app import crud

from app.db import get_db

router = APIRouter()

@router.get("/initial-users", response_model=dict)
async def create_initial_users(db: AsyncSession = Depends(get_db)):
    """
    초기 관리자 및 사용자 계정을 생성합니다.
    (주의: 프로덕션 환경에서는 이 엔드포인트를 비활성화하거나 삭제해야 합니다.)
    """
    
    actions_log = []

    # --- 관리자 계정 정보 ---
    admin_user_email = "admin@example.com"
    admin_user_password = "adminpassword"
    
    admin_user = await crud.user.get_user_by_email(db, email=admin_user_email)
    if not admin_user:
        user_in = user_schema.UserCreate(
            email=admin_user_email,
            password=admin_user_password,
            role="admin"
        )
        await crud.user.create_user(db, user_in) # 이 부분은 정상
        actions_log.append(f"Admin user '{admin_user_email}' created.")
    else:
         actions_log.append(f"Admin user '{admin_user_email}' already exists.")

    # --- 일반 사용자 계정 정보 ---
    normal_user_email = "user@example.com"
    normal_user_password = "userpassword"

    normal_user = await crud.user.get_user_by_email(db, email=normal_user_email)
    if not normal_user:
        user_in = user_schema.UserCreate(
            email=normal_user_email,
            password=normal_user_password,
            role="user"
        )
        # --- [수정] 누락된 'user' 모듈 경로 추가 ---
        await crud.user.create_user(db, user_in)
        actions_log.append(f"Normal user '{normal_user_email}' created.")
    else:
        actions_log.append(f"Normal user '{normal_user_email}' already exists.")

    return {"status": "success", "actions": actions_log}
