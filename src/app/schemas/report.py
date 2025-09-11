# src/app/schemas/report.py

from pydantic import BaseModel, Field
from typing import List, Dict

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