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
    turn_number: int = Field(default=0, description="현재 토론 라운드 번호 (0부터 시작)")
    completed_at: Optional[datetime] = None
    report_summary: Optional[str] = None

    # API 응답에 핵심 자료집 필드 추가
    evidence_briefing: Optional[Dict[str, Any]] = None
    
    # UX 데이터 필드 추가
    round_summary: Optional[Dict[str, Any]] = None
    flow_data: Optional[Dict[str, Any]] = None
    
    current_vote: Optional[Dict[str, Any]] = Field(default=None, description="현재 진행 중인 투표의 주제와 선택지")
    
    class Config:
        from_attributes = True 

class VoteContent(BaseModel):
    """AI가 생성한 투표의 주제와 선택지를 정의하는 모델"""
    topic: str = Field(description="투표의 주제가 될 질문입니다.")
    options: List[str] = Field(description="사용자가 선택할 2~4개의 선택지 목록입니다.")

    class Config:
        from_attributes = True

class Interaction(BaseModel):
    """단일 상호작용을 정의하는 모델"""
    from_agent: str = Field(..., alias="from")
    to_agent: str = Field(..., alias="to")
    interaction_type: Literal["agreement", "disagreement"] = Field(..., alias="type")

class InteractionAnalysisResult(BaseModel):
    """Interaction Analyst의 분석 결과를 담는 모델"""
    interactions: List[Interaction]