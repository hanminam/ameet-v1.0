# src/app/api/v1/admin/users.py

from fastapi import APIRouter, Depends
from typing import List

from app.api.v1.users import get_current_admin_user
from app.crud import user as user_crud
from app.schemas import user as user_schema
from app.models.user import User as UserModel

router = APIRouter()

@router.get("/", response_model=List[user_schema.User])
async def read_all_users_for_admin(
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """
    (Admin Only) 'user' 역할을 가진 모든 사용자 목록을 조회합니다.
    가입일 기준 최신순으로 정렬됩니다.
    """
    users = await user_crud.get_users_by_role(role="user")
    return users