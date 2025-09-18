# src/app/api/v1/admin/users.py

from fastapi import APIRouter, Depends, HTTPException
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

# --- 사용자 정보 수정 API ---
@router.put("/{user_id}", response_model=user_schema.User)
async def update_user_by_admin(
    user_id: str,
    user_update: user_schema.UserUpdate,
    admin_user: user_schema.User = Depends(get_current_admin_user)
):
    """(Admin Only) ID로 특정 사용자의 정보를 수정합니다."""
    updated_user = await user_crud.update_user(user_id, user_update)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return updated_user

# --- 사용자 삭제 API ---
@router.delete("/{user_id}", response_model=user_schema.User)
async def delete_user_by_admin(
    user_id: str,
    admin_user: user_schema.User = Depends(get_current_admin_user)
):
    """(Admin Only) ID로 특정 사용자를 삭제합니다."""
    deleted_user = await user_crud.delete_user(user_id=user_id)
    if deleted_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return deleted_user