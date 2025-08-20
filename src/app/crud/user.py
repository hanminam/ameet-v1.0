from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from ..models.user import User
from ..schemas import UserCreate
from ..core.security import get_password_hash

async def get_user_by_email(db: AsyncSession, email: str):
    result = await db.execute(select(User).filter(User.email == email))
    return result.scalars().first()

async def create_user(db: AsyncSession, user: UserCreate):
    hashed_password = get_password_hash(user.password)
    db_user = User(
        email=user.email,
        hashed_password=hashed_password,
        role=user.role
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

async def get_user(db: AsyncSession, user_id: int):
    """ID로 단일 사용자 조회"""
    result = await db.execute(select(User).filter(User.id == user_id))
    return result.scalars().first()

async def get_users(db: AsyncSession, skip: int = 0, limit: int = 100):
    """사용자 목록 조회 (페이지네이션)"""
    result = await db.execute(select(User).offset(skip).limit(limit))
    return result.scalars().all()

async def delete_user(db: AsyncSession, user_id: int):
    """사용자 삭제"""
    user = await get_user(db, user_id=user_id)
    if user:
        await db.delete(user)
        await db.commit()
    return user