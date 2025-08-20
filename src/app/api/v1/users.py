from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError
from app import schemas, crud, models
from app.core import security
from app.db import AsyncDBSession
from app.db import get_db

router = APIRouter()

# --- 인증 의존성 (Security Dependency) ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login/token")

async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: AsyncSession = Depends(get_db)
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = security.jwt.decode(
            token, security.settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        email: str = payload.get("sub")
        role: str = payload.get("role")
        if email is None or role is None:
            raise credentials_exception
        token_data = schemas.TokenData(email=email, role=role)
    except JWTError:
        raise credentials_exception
    
    user = await crud.get_user_by_email(db, email=token_data.email)
    if user is None:
        raise credentials_exception
    return user

# --- [핵심] 관리자 역할 확인 의존성 ---
async def get_current_admin_user(current_user: models.User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges"
        )
    return current_user

# --- 관리자 전용 API 엔드포인트 ---

@router.post("/", response_model=schemas.User, status_code=status.HTTP_201_CREATED)
async def create_user_by_admin(
    user: schemas.UserCreate,
    db: AsyncSession = Depends(get_db),
    admin_user: models.User = Depends(get_current_admin_user)
):
    """
    (관리자 전용) 새로운 사용자를 생성합니다.
    """
    db_user = await crud.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    return await crud.create_user(db=db, user=user)

@router.get("/", response_model=List[schemas.User])
async def read_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(lambda: AsyncDBSession()),
    admin_user: models.User = Depends(get_current_admin_user)
):
    """
    (관리자 전용) 사용자 목록을 조회합니다.
    """
    users = await crud.user.get_users(db, skip=skip, limit=limit)
    return users

@router.delete("/{user_id}", response_model=schemas.User)
async def delete_user_by_admin(
    user_id: int,
    db: AsyncSession = Depends(lambda: AsyncDBSession()),
    admin_user: models.User = Depends(get_current_admin_user)
):
    """
    (관리자 전용) ID로 사용자를 삭제합니다.
    """
    db_user = await crud.user.delete_user(db, user_id=user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user