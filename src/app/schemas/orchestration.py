# src/app/schemas/orchestration.py

from pydantic import BaseModel, Field
from typing import List
from datetime import date

class KeyIssue(BaseModel):
    """개별 주요 쟁점을 정의하는 모델"""
    issue: str = Field(description="토론 주제에서 파생된 핵심적인 질문 또는 논쟁점입니다.")
    description: str = Field(description="이것이 왜 핵심 쟁점인지에 대한 간략한 설명입니다.")

class IssueAnalysisReport(BaseModel):
    """
    토론 주제의 핵심 요소를 분석한 구조화된 보고서입니다.
    """
    core_keywords: List[str] = Field(
        description="토론 주제를 정의하는 가장 본질적인 키워드 목록입니다."
    )
    key_issues: List[KeyIssue] = Field(
        description="토론에서 다뤄져야 할 주요 쟁점 또는 질문 목록입니다."
    )
    anticipated_perspectives: List[str] = Field(
        description="이 주제에 대한 토론에서 예상되는 다양한 관점이나 입장 목록입니다. (예: 긍정, 부정, 경제적 관점, 사회적 관점 등)"
    )

# --- 증거 수집 단계에서 사용할 모델 ---
class EvidenceItem(BaseModel):
    """단일 증거 자료 항목을 정의하는 모델"""
    source: str = Field(description="정보의 출처 (예: 웹사이트 URL, 파일 이름)")
    publication_date: str = Field(description="자료의 발행일 또는 확인된 날짜 (YYYY-MM-DD 형식)", default_factory=lambda: date.today().isoformat())
    summary: str = Field(description="자료의 핵심 내용을 요약한 문장입니다.")

class CoreEvidenceBriefing(BaseModel):
    """
    웹 검색과 사용자 파일을 종합하여 생성된 핵심 자료집입니다.
    """
    web_evidence: List[EvidenceItem] = Field(description="웹 검색을 통해 수집된 증거 자료 목록입니다.")
    file_evidence: List[EvidenceItem] = Field(description="사용자가 업로드한 파일에서 추출된 증거 자료 목록입니다.")

# --- 배심원단 선정 단계에서 사용할 모델 ---
class SelectedJury(BaseModel):
    """LLM이 선택한 배심원단과 그 선정 이유를 정의하는 모델"""
    agent_names: List[str] = Field(
        description="토론에 참여할 5~10명의 전문가 에이전트 이름 목록입니다."
    )
    reason: str = Field(
        description="이 배심원단을 구성한 이유에 대한 간략한 설명입니다."
    )

class DebateTeam(BaseModel):
    """최종적으로 구성된 재판관과 배심원단 팀 정보"""
    judge: str = Field(description="토론의 사회자로 지정된 재판관 에이전트의 이름입니다.")
    jury: List[str] = Field(description="토론에 참여하는 전문가 배심원단 목록입니다.")
    reason: str = Field(description="배심원단 선정 이유입니다.")