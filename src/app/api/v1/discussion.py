# src/app/api/v1/discussion.py

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File

from app.services import orchestrator
from app.schemas.orchestration import DebateTeam
from app.api.v1.users import get_current_user # 사용자 인증
from app.models.user import User as UserModel

router = APIRouter()

@router.post("/orchestrate", response_model=DebateTeam)
async def run_orchestration_pipeline(
    topic: str = Form(...),
    file: Optional[UploadFile] = File(None),
    current_user: UserModel = Depends(get_current_user) # 요청 시 JWT 인증 필요
):
    """
    주제와 파일을 입력받아 '재판 준비' 3단계 파이프라인을 실행하고
    최종 토론 팀 구성을 반환합니다.
    """
    try:
        # 1단계: 사건 분석
        analysis_report = await orchestrator.analyze_topic(topic)
        
        # 2단계: 증거 수집
        files_to_process = [file] if file else []
        evidence_briefing = await orchestrator.gather_evidence(
            report=analysis_report, 
            files=files_to_process,
            topic=topic
        )
        
        # 3단계: 배심원단 선정
        # (현재 증거 자료집은 배심원단 선정에 직접 사용되지 않지만, 향후 확장성을 위해 전달)
        debate_team = await orchestrator.select_debate_team(analysis_report)
        
        return debate_team
        
    except Exception as e:
        # 실제 운영 환경에서는 에러 로깅이 필요합니다.
        print(f"Orchestration Error: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred during orchestration: {e}")