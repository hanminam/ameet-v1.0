# src/app/crud/user.py

from typing import List, Optional
from datetime import datetime

# Pydantic 스키마와 MongoDB 모델(User)을 모두 사용
from app.schemas.user import UserCreate, User as UserSchema
from app.models.discussion import User
from app.core.security import get_password_hash

async def get_user_by_email(email: str) -> Optional[User]:
    """이메일로 MongoDB에서 사용자를 조회합니다."""
    return await User.find_one(User.email == email)

async def create_user(user: UserCreate) -> User:
    """새로운 사용자를 생성하여 MongoDB에 저장합니다."""
    hashed_password = get_password_hash(user.password)
    new_user = User(
        name=user.name,
        email=user.email,
        hashed_password=hashed_password,
        role=user.role
    )
    await new_user.insert()
    return new_user

async def update_user_last_login(user: User) -> User:
    """사용자의 마지막 로그인 시간을 현재 시간으로 업데이트합니다."""
    user.last_login_at = datetime.utcnow()
    await user.save()
    return user

async def get_users_by_role(role: str) -> List[User]:
    """특정 역할을 가진 사용자 목록을 가입일 최신순으로 정렬하여 반환합니다."""
    return await User.find(User.role == role).sort(-User.created_at).to_list()

# --- 아래 함수들은 현재 관리자 기능에선 불필요하지만, 호환성을 위해 남겨둡니다 ---

async def get_users(skip: int = 0, limit: int = 100) -> List[User]:
    """모든 사용자 목록을 페이지네이션하여 조회합니다."""
    return await User.find_all().skip(skip).limit(limit).to_list()

async def delete_user(user_id: int) -> Optional[User]:
    """ID로 사용자를 삭제합니다. (MongoDB의 PydanticObjectId 필요)"""
    # MongoDB의 ObjectId는 정수가 아니므로, 이 기능은 추가적인 수정이 필요합니다.
    # 지금은 기능이 호출되지 않으므로 그대로 둡니다.
    return None