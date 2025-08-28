# src/app/schemas/discussion.py

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Literal, Optional
from datetime import datetime

class DiscussionLogItem(BaseModel):
    """토론 목록의 개별 항목을 위한 스키마"""
    discussion_id: str
    topic: str
    status: str # Literal 타입 대신 string으로 유연하게 처리
    created_at: datetime
    user_email: str

    class Config:
        from_attributes = True

class DiscussionLogDetail(DiscussionLogItem):
    """토론 상세 조회를 위한 스키마"""
    transcript: List[Dict[str, Any]]
    participants: Optional[List[Dict[str, Any]]] = None
    completed_at: Optional[datetime] = None
    report_summary: Optional[str] = None
    
    # UX 데이터 필드 추가
    round_summary: Optional[Dict[str, Any]] = None
    flow_data: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True 