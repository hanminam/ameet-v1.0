# src/app/api/v1/users.py

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError, jwt

from app.schemas import user as user_schema
from app import crud

from app.core import security
from app.db import get_db
from app.models.user import User as UserModel # UserModel 별칭으로 명확하게 임포트

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login/token")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserModel:
    """Decodes the JWT token to get the current user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, security.settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        email: str = payload.get("sub")
        role: str = payload.get("role")
        if email is None or role is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = await crud.user.get_user_by_email(email=email)
    if user is None:
        raise credentials_exception
    return user

async def get_current_admin_user(current_user: UserModel = Depends(get_current_user)) -> UserModel:
    """Ensures the current user has the 'admin' role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges"
        )
    return current_user

@router.post("/", response_model=user_schema.User, status_code=status.HTTP_201_CREATED)
async def create_user_by_admin(
    user: user_schema.UserCreate,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """(Admin Only) Creates a new user in the users.json file."""
    db_user = await crud.user.get_user_by_email(email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    return await crud.user.create_user(user=user)

@router.get("/", response_model=List[user_schema.User])
async def read_users(
    skip: int = 0,
    limit: int = 100,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """(Admin Only) Reads a list of users from the users.json file."""
    users = await crud.user.get_users(skip=skip, limit=limit)
    return users

@router.delete("/{user_id}", response_model=user_schema.User)
async def delete_user_by_admin(
    user_id: int,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """(Admin Only) Deletes a user by ID from the users.json file."""
    db_user = await crud.user.delete_user(user_id=user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user