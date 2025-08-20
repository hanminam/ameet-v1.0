# src/app/models/user.py

from sqlalchemy import Column, Integer, String, DateTime, func, Enum as SQLAlchemyEnum
from .base import Base  # 새로 만든 base.py에서 Base를 가져옵니다.

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    # [신규] 역할(role) 컬럼 추가
    role = Column(SQLAlchemyEnum('user', 'admin', name='user_roles'), nullable=False, server_default='user')
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())