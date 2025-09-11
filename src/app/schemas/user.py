from pydantic import BaseModel, EmailStr
from typing import Literal

# --- Token ---

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: EmailStr
    role: str

# --- User ---

class UserBase(BaseModel):
    email: EmailStr
    name: str

class UserCreate(UserBase):
    password: str
    role: Literal['admin', 'user'] = 'user'

class User(UserBase):
    id: int
    role: str
    hashed_password: str

class UserInDB(User):
    pass
