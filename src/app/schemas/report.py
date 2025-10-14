# src/app/schemas/report.py

from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Literal, Any, Optional
import json

class ChartRequest(BaseModel):
    """'Report Component Planner'가 생성하는 개별 차트 실행 계획"""
    chart_title: str = Field(description="보고서에 표시될 차트의 최종 제목")
    tool_name: Literal["get_stock_price", "get_economic_data"] = Field(description="차트 데이터 조회에 사용할 도구의 이름")
    tool_args: Dict[str, str] = Field(description="도구 호출 시 전달할 인자 딕셔너리 (예: {'ticker': 'TSLA', 'start_date': '...'})")

    @field_validator('tool_args', mode='before')
    @classmethod
    def parse_tool_args(cls, v: Any) -> Any:
        """LLM이 tool_args를 문자열 형태의 JSON으로 반환했을 경우, 파싱하여 dict로 변환합니다."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # 파싱에 실패하면 Pydantic의 기본 유효성 검사가 오류를 발생시키도록 함
                pass
        return v

class ReportStructure(BaseModel):
    """ Report Component Planner가 생성할 보고서의 유연한 구조 모델"""
    title: str = Field(description="보고서의 메인 제목") # 제목은 필수로 유지
    
    subtitle: Optional[str] = Field(default=None, description="보고서의 부제")
    
    expert_opinions: List[Dict[str, str]] = Field(
        default_factory=list, description="전문가별 핵심 의견 요약 리스트"
    )
    
    key_factors: Optional[Dict[str, List[str]]] = Field(
        default_factory=dict, description="긍정적/부정적 핵심 요인"
    )
    
    conclusion: Optional[str] = Field(default=None, description="토론을 통해 도출된 최종 결론")
    
    chart_requests: List[ChartRequest] = Field(
        default_factory=list, description="보고서에 포함되어야 할 실행 가능한 차트 요청 목록"
    )

    @field_validator('key_factors', 'expert_opinions', mode='before')
    @classmethod
    def parse_str_json(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                pass
        return v

class ResolverOutput(BaseModel):
    """Ticker/ID Resolver 에이전트의 JSON 출력 형식"""
    type: Literal["stock", "economic"] = Field(description="데이터의 종류")
    id: str = Field(description="조회에 사용될 티커 또는 시리즈 ID")

#class ChartJsData(BaseModel):
#    """Chart.js 라이브러리와 호환되는 차트 데이터 구조 또는 오류 메시지"""
#    labels: Optional[List[str]] = None
#    datasets: Optional[List[Dict[str, Any]]] = None
#    error: Optional[str] = None

# OutlineGenerator의 출력을 받을 Pydantic 모델
class ReportOutline(BaseModel):
    title: str = Field(description="보고서의 전체 제목")
    subtitle: Optional[str] = Field(default=None, description="보고서의 부제")
    executive_summary: str = Field(description="토론 전체를 2~3문장으로 요약한 핵심 결론")
    pro_arguments: List[str] = Field(default_factory=list, description="토론의 주요 긍정/찬성 논거 목록")
    con_arguments: List[str] = Field(default_factory=list, description="토론의 주요 부정/반대 논거 목록")
    overall_conclusion: str = Field(description="토론 내용을 종합하여 AI가 내리는 최종 결론 및 제언")
    chart_worthy_entities: List[str] = Field(default_factory=list, description="차트 생성이 유의미한 핵심 개체 목록")

# ChartPlanValidator의 출력을 받을 Pydantic 모델
class ValidatedChartPlan(BaseModel):
    chart_requests: List[ChartRequest] = Field(default_factory=list)