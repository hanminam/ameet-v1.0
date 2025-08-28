# src/app/models/discussion.py

from beanie import Document, Indexed
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Literal, Optional, Annotated
from datetime import datetime

# --- DiscussionLog 모델 ---
class DiscussionLog(Document):
    """토론의 전체 대화 기록을 저장하는 모델"""
    discussion_id: Annotated[str, Indexed(unique=True)]
    
    status: Literal[
        "orchestrating",      # 1. 팀 구성 및 오케스트레이션 진행 중 
        "ready",              # 2. 팀 구성 완료, 첫 턴 시작 대기 중 
        "turn_inprogress",    # 3. 특정 턴(예: 모두 변론)이 진행 중 
        "turn_complete",      # 4. 턴 완료, 다음 턴 또는 사용자 입력 대기 중
        "waiting_for_vote",   # 5. 사용자 투표/피드백 대기 중 
        "completed",          # 6. 모든 토론 절차 완료 
        "failed"              # 7. 오류로 인한 실패 
    ] = "orchestrating"

    # --- 토론 참여자 정보를 저장하는 필드 ---
    participants: Optional[List[Dict[str, Any]]] = None # 유연한 저장을 위해 Dict 사용
    
    topic: str
    user_email: Annotated[str, Indexed()]
    transcript: List[Dict[str, Any]] = Field(default_factory=list)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    report_summary: Optional[str] = None

    # --- UX 데이터 필드 ---
    flow_data: Optional[Dict[str, Any]] = Field(default=None, description="라운드별 에이전트 상호작용 데이터")
    round_summary: Optional[Dict[str, Any]] = Field(default=None, description="라운드별 결정적 발언, 입장 변화 데이터")
    
    class Settings:
        name = "discussions"


# --- 에이전트의 실제 설정을 담는 Pydantic 모델 ---
class AgentConfig(BaseModel):
    """에이전트의 프롬프트, 모델 등 실제 설정 값을 담는 모델"""
    prompt: str
    model: str
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    tools: List[str] = Field(default_factory=list, description="에이전트가 사용할 도구 목록 (예: ['web_search'])")
    icon: Optional[str] = Field(default="🤖", description="UI에 표시될 이모지 아이콘")


# --- AgentSettings 모델을 버전/상태 관리가 가능하도록 재설계 ---
class AgentSettings(Document):
    """
    에이전트 설정을 관리하는 MongoDB Document 모델.
    버전과 상태 관리를 통해 안전한 수정 및 배포 워크플로우를 지원합니다.
    """
    name: str = Field(description="에이전트의 고유한 이름 (예: '재무 분석가')")
    agent_type: Literal["special", "expert"] = Field(description="에이전트의 타입")
    
    # --- 상태 및 버전 관리를 위한 핵심 필드 ---
    version: int = Field(default=1, description="설정 변경 이력을 위한 버전 번호")
    status: Literal["active", "archived", "draft"] = Field(
        default="active", 
        description="active: 실 서비스용, archived: 비활성/삭제됨, draft: 수정 중인 초안"
    )
    
    # --- 실제 설정 값 (내장 모델) ---
    config: AgentConfig
    
    # --- 감사(Audit)를 위한 필드 ---
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    # user.email과 연결하여 어떤 관리자가 수정했는지 추적 가능
    last_modified_by: Optional[str] = Field(default=None)

    class Settings:
        name = "agents"
        # 쿼리 성능 향상을 위한 인덱스 설정
        indexes = [
            [("name", 1), ("version", -1)], 
            [("status", 1)],
            [("name", 1), ("status", 1)]
        ]