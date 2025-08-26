# src/app/schemas/discussion.py

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Literal, Optional
from datetime import datetime

class DiscussionLogItem(BaseModel):
    """토론 목록의 개별 항목을 위한 스키마"""
    discussion_id: str
    topic: str
    status: Literal["processing", "completed", "failed"]
    created_at: datetime
    user_email: str

    class Config:
        from_attributes = True # ORM 모델을 Pydantic 모델로 변환 허용

class DiscussionLogDetail(DiscussionLogItem):
    """토론 상세 조회를 위한 스키마"""
    transcript: List[Dict[str, Any]]
    completed_at: Optional[datetime] = None
    report_summary: Optional[str] = None
    
    class Config:
        from_attributes = True