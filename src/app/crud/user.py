# src/app/crud/user.py

from typing import List, Optional
from datetime import datetime, timezone

# Pydantic 스키마와 MongoDB 모델(User)을 모두 사용
from app.schemas.user import UserCreate, User as UserSchema, UserUpdate 
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
    user.last_login_at = datetime.now(timezone.utc)
    await user.save()
    return user

async def get_users_by_role(role: str) -> List[User]:
    """특정 역할을 가진 사용자 목록을 가입일 최신순으로 정렬하여 반환합니다."""
    return await User.find(User.role == role).sort(-User.created_at).to_list()

# --- 아래 함수들은 현재 관리자 기능에선 불필요하지만, 호환성을 위해 남겨둡니다 ---

async def get_users(skip: int = 0, limit: int = 100) -> List[User]:
    """모든 사용자 목록을 페이지네이션하여 조회합니다."""
    return await User.find_all().skip(skip).limit(limit).to_list()

# --- 사용자 정보 업데이트 함수 ---
async def update_user(user_id: str, user_update: UserUpdate) -> Optional[User]:
    """ID로 사용자를 찾아 정보를 업데이트합니다."""
    user = await User.get(user_id)
    if not user:
        return None

    update_data = user_update.model_dump(exclude_unset=True)

    # 비밀번호가 제공된 경우, 해시하여 업데이트
    if "password" in update_data and update_data["password"]:
        hashed_password = get_password_hash(update_data["password"])
        user.hashed_password = hashed_password
        del update_data["password"] # 해시된 값으로 대체했으므로 제거

    # 나머지 필드 업데이트
    for key, value in update_data.items():
        setattr(user, key, value)
    
    await user.save()
    return user

# --- 사용자 삭제 함수 (ID 타입을 int에서 str으로 변경) ---
async def delete_user(user_id: str) -> Optional[User]:
    """ID로 사용자를 찾아 삭제합니다."""
    user = await User.get(user_id)
    if user:
        await user.delete()
        return user
    return None