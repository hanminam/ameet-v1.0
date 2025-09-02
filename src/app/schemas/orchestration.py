# src/app/schemas/orchestration.py

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date

# --- 1단계: 주제 분석 모델 ---
class KeyIssue(BaseModel):
    """개별 주요 쟁점을 정의하는 모델"""
    issue: str = Field(description="토론 주제에서 파생된 핵심적인 질문 또는 논쟁점입니다.")
    description: str = Field(description="이것이 왜 핵심 쟁점인지에 대한 간략한 설명입니다.")

class IssueAnalysisReport(BaseModel):
    """토론 주제의 핵심 요소를 분석한 구조화된 보고서입니다."""
    core_keywords: List[str] = Field(description="토론 주제를 정의하는 가장 본질적인 키워드 목록입니다.")
    key_issues: List[KeyIssue] = Field(description="토론에서 다뤄져야 할 주요 쟁점 또는 질문 목록입니다.")
    anticipated_perspectives: List[str] = Field(description="이 주제에 대한 토론에서 예상되는 다양한 관점이나 입장 목록입니다.")

# --- 2단계: 증거 수집 모델 ---
class EvidenceItem(BaseModel):
    """단일 증거 자료 항목을 정의하는 모델"""
    source: str = Field(description="정보의 출처 (예: 웹사이트 URL, 파일 이름)")
    publication_date: str = Field(description="자료의 발행일 또는 확인된 날짜 (YYYY-MM-DD 형식)", default_factory=lambda: date.today().isoformat())
    summary: str = Field(description="자료의 핵심 내용을 요약한 문장입니다.")

class CoreEvidenceBriefing(BaseModel):
    """웹 검색과 사용자 파일을 종합하여 생성된 핵심 자료집입니다."""
    web_evidence: List[EvidenceItem] = Field(description="웹 검색을 통해 수집된 증거 자료 목록입니다.")
    file_evidence: List[EvidenceItem] = Field(description="사용자가 업로드한 파일에서 추출된 증거 자료 목록입니다.")

# --- 3단계: 배심원단 선정 모델 ---

# LLM의 응답을 받을 Pydantic 모델
class SelectedJury(BaseModel):
    """LLM이 선택한 배심원단과 그 선정 이유, 신규 제안을 정의하는 모델"""
    selected_agents: List[str] = Field(
        description="토론에 참여할 기존 전문가 에이전트 이름 목록입니다."
    )
    new_agent_proposals: Optional[List[str]] = Field(
        default_factory=list,
        description="기존 풀에 없어 새로 생성이 필요하다고 판단되는 전문가 역할 목록입니다."
    )
    reason: str = Field(
        description="이 배심원단을 구성하고, 새로운 전문가를 제안한 이유에 대한 설명입니다."
    )

# 최종 API 응답 및 내부 데이터 전달에 사용될 모델
class AgentDetail(BaseModel):
    """에이전트의 상세 정보를 담는 모델"""
    name: str
    model: str
    prompt: str
    temperature: float
    tools: Optional[List[str]] = Field(default_factory=list)
    icon: Optional[str] = Field(default="🤖", description="UI에 표시될 이모지 아이콘")

class DebateTeam(BaseModel):
    """최종적으로 구성된 재판관과 배심원단 팀 정보"""
    discussion_id: str = Field(description="이번 토론 세션을 식별하는 고유 ID입니다.")
    judge: AgentDetail
    jury: List[AgentDetail]
    reason: str