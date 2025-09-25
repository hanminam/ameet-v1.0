# src/app/crud/user.py

from typing import List, Optional
from datetime import datetime, timezone
from bson import ObjectId  # [수정] MongoDB의 ObjectId를 직접 사용하기 위해 임포트

# Pydantic 스키마와 MongoDB 모델(User)을 모두 사용
from app.schemas.user import UserCreate, UserUpdate
from app.models.discussion import User
from app.core.security import get_password_hash
from app import db # [수정] db 모듈 임포트
from app.core.config import settings

# [신규] DB 컬렉션을 가져오는 헬퍼 함수
def get_user_collection():
    db_name = settings.MONGO_DB_URL.split("/")[-1].split("?")[0]
    return db.mongo_client[db_name]["users"]

async def get_user_by_email(email: str) -> Optional[User]:
    """이메일로 MongoDB에서 사용자를 조회합니다."""
    collection = get_user_collection()
    user_data = await collection.find_one({"email": email})
    if user_data:
        return User.model_validate(user_data)
    return None

async def get_user_by_id(user_id: str) -> Optional[User]:
    """ID로 MongoDB에서 사용자를 조회합니다."""
    collection = get_user_collection()
    user_data = await collection.find_one({"_id": ObjectId(user_id)})
    if user_data:
        return User.model_validate(user_data)
    return None

async def create_user(user: UserCreate) -> User:
    """새로운 사용자를 생성하여 MongoDB에 저장합니다."""
    collection = get_user_collection()
    hashed_password = get_password_hash(user.password)
    
    # Beanie 모델을 사용하여 데이터 구조를 만들고 dict로 변환
    new_user_model = User(
        name=user.name,
        email=user.email,
        hashed_password=hashed_password,
        role=user.role
    )
    # Pydantic 모델의 기본값을 포함하여 DB에 저장할 dict 생성
    user_dict_to_insert = new_user_model.model_dump(exclude={"id"})

    result = await collection.insert_one(user_dict_to_insert)
    
    # 삽입된 문서를 다시 조회하여 완전한 User 객체로 반환
    created_user_data = await collection.find_one({"_id": result.inserted_id})
    return User.model_validate(created_user_data)


async def update_user_last_login(user: User) -> User:
    """사용자의 마지막 로그인 시간을 현재 시간으로 업데이트합니다."""
    collection = get_user_collection()
    new_login_time = datetime.now(timezone.utc)
    await collection.update_one(
        {"_id": user.id},
        {"$set": {"last_login_at": new_login_time}}
    )
    user.last_login_at = new_login_time
    return user

async def get_users_by_role(role: str) -> List[User]:
    """특정 역할을 가진 사용자 목록을 가입일 최신순으로 정렬하여 반환합니다."""
    collection = get_user_collection()
    users_cursor = collection.find({"role": role}).sort("created_at", -1)
    users_data = await users_cursor.to_list(length=None)
    return [User.model_validate(user) for user in users_data]

async def get_users(skip: int = 0, limit: int = 100) -> List[User]:
    """모든 사용자 목록을 페이지네이션하여 조회합니다."""
    collection = get_user_collection()
    users_cursor = collection.find().skip(skip).limit(limit)
    users_data = await users_cursor.to_list(length=None)
    return [User.model_validate(user) for user in users_data]

async def update_user(user_id: str, user_update: UserUpdate) -> Optional[User]:
    """ID로 사용자를 찾아 정보를 업데이트합니다."""
    collection = get_user_collection()
    update_data = user_update.model_dump(exclude_unset=True)

    if "password" in update_data and update_data["password"]:
        hashed_password = get_password_hash(update_data["password"])
        update_data["hashed_password"] = hashed_password
        del update_data["password"]

    if not update_data:
        return await get_user_by_id(user_id) # 변경 사항이 없으면 현재 사용자 정보 반환

    result = await collection.find_one_and_update(
        {"_id": ObjectId(user_id)},
        {"$set": update_data},
        return_document=True
    )
    if result:
        return User.model_validate(result)
    return None

async def delete_user(user_id: str) -> Optional[User]:
    """ID로 사용자를 찾아 삭제합니다."""
    collection = get_user_collection()
    user_to_delete = await collection.find_one_and_delete({"_id": ObjectId(user_id)})
    if user_to_delete:
        return User.model_validate(user_to_delete)
    return None