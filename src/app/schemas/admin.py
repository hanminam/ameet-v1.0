# src/app/schemas/admin.py

from pydantic import BaseModel, Field
from typing import List
from datetime import datetime

class TurnUsageDetail(BaseModel):
    """토론의 각 Turn(단계)별 상세 사용량"""
    turn_name: str = Field(description="해당 LLM 호출의 단계 이름 (예: 'Topic Analyst', '재무 분석가')")
    model_name: str = Field(description="사용된 LLM 모델 이름")
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float = Field(description="해당 Turn에서 발생한 비용 (USD)")
    latency_ms: float = Field(description="응답 지연 시간 (밀리초)")
    start_time: datetime

class AgentCostSummary(BaseModel):
    """에이전트별 비용 및 토큰 사용량 요약 (차트용)"""
    agent_name: str
    total_cost_usd: float
    total_tokens: int

class DiscussionUsageResponse(BaseModel):
    """'/usage' 엔드포인트의 최종 응답 모델"""
    discussion_id: str
    topic: str
    user_email: str
    total_cost_usd: float = Field(description="토론 전체에서 발생한 총비용 (USD)")
    total_tokens: int
    start_time: datetime
    duration_seconds: float
    turn_details: List[TurnUsageDetail] = Field(description="단계별 상세 사용 내역 (테이블용)")
    agent_summary: List[AgentCostSummary] = Field(description="에이전트별 비용 요약 (도넛 차트용)")

class UsageSummaryResponse(BaseModel):
    """대시보드 상단 카드에 표시될 사용량 요약 정보"""
    total_cost_this_month: float
    total_discussions_this_month: int
    average_cost_per_discussion: float