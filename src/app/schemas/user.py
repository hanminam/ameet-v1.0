from pydantic import BaseModel, EmailStr, Field
from typing import Literal, Optional
from datetime import datetime
from beanie import PydanticObjectId

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
    # MongoDB의 '_id' 필드를 PydanticObjectId 타입의 'id' 필드로 매핑
    id: PydanticObjectId = Field(..., alias='_id')
    
    role: str
    # 참고: 보안을 위해 API 응답에서 비밀번호 필드는 제외하는 것이 좋습니다.
    # 여기서는 기존 구조를 유지합니다.
    hashed_password: str

    # datetime 객체를 직접 받도록 타입 변경
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    
    class Config:
        # Beanie/MongoDB 모델 객체를 Pydantic 모델로 변환하기 위한 설정
        from_attributes = True
        populate_by_name = True  # 'alias'를 사용하기 위해 필요
        arbitrary_types_allowed = True # ObjectId와 같은 임의 타입을 허용
        json_encoders = {
            # 최종 JSON 응답으로 변환될 때 ObjectId는 문자열로 변환
            PydanticObjectId: str 
        }

class UserInDB(User):
    pass
