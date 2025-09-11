# src/app/schemas/report.py

from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Literal, Any, Optional
import json

class ChartRequest(BaseModel):
    """보고서에 포함될 차트 생성을 위한 요청 모델"""
    chart_title: str = Field(description="차트의 제목 (예: '테슬라 최근 6개월 주가 추이')")
    required_data_description: str = Field(description="차트 생성에 필요한 데이터에 대한 자연어 설명")
    suggested_chart_type: str = Field(description="추천하는 차트 종류 (예: 'line_chart')")

class ReportStructure(BaseModel):
    """Report Component Planner가 생성할 보고서의 전체 구조 모델"""
    title: str = Field(description="보고서의 메인 제목")
    subtitle: str = Field(description="보고서의 부제")
    expert_opinions: List[Dict[str, str]] = Field(description="전문가별 핵심 의견 요약 리스트")
    key_factors: Dict[str, List[str]] = Field(description="긍정적/부정적 핵심 요인")
    conclusion: str = Field(description="토론을 통해 도출된 최종 결론")
    chart_requests: List[ChartRequest] = Field(description="보고서에 포함되어야 할 차트 요청 목록")

    @field_validator('key_factors', 'expert_opinions', mode='before')
    @classmethod
    def parse_str_json(cls, v: Any) -> Any:
        """LLM이 dict나 list를 string 형태로 반환했을 경우, 파싱하여 원래 타입으로 변환합니다."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # 파싱에 실패하면 원래 유효성 검사 로직이 처리하도록 그대로 둡니다.
                pass
        return v

class ResolverOutput(BaseModel):
    """Ticker/ID Resolver 에이전트의 JSON 출력 형식"""
    type: Literal["stock", "economic"] = Field(description="데이터의 종류")
    id: str = Field(description="조회에 사용될 티커 또는 시리즈 ID")

class ChartJsData(BaseModel):
    """Chart.js 라이브러리와 호환되는 차트 데이터 구조 또는 오류 메시지"""
    labels: Optional[List[str]] = None
    datasets: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None