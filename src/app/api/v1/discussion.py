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
    current_user: UserModel = Depends(get_current_user)
):
    try:
        # 1. 설정 파일 미리 로드
        special_agents = orchestrator._load_agent_configs("app/core/settings/special_agents.json")
        jury_pool = orchestrator._load_agent_configs("app/core/settings/agents.json")

        # --- 2. 1단계: 사건 분석 함수 호출 시, special_agents 인자 전달 ---
        analysis_report = await orchestrator.analyze_topic(topic, special_agents)
        
        # 3. 2단계: 증거 수집
        files_to_process = [file] if file else []
        evidence_briefing = await orchestrator.gather_evidence(
            report=analysis_report, 
            files=files_to_process,
            topic=topic
        )
        
        # 4. 3단계: 배심원단 선정
        debate_team = await orchestrator.select_debate_team(analysis_report, jury_pool, special_agents)
        
        return debate_team
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An error occurred during orchestration: {e}")