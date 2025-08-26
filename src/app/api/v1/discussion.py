# src/app/api/v1/discussion.py

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File

from app.services.orchestrator import (
    get_active_agents_from_db, # DB 조회 함수 임포트
    analyze_topic,
    gather_evidence,
    select_debate_team
)
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
        # 1. 고유한 토론 ID 생성
        discussion_id = f"dscn_{uuid.uuid4()}"
        
        # 2. DB에서 에이전트 설정 가져오기
        special_agents, jury_pool = await get_active_agents_from_db()
        
        # 3. 각 단계별 함수 호출 시 discussion_id 전달
        analysis_report = await analyze_topic(topic, special_agents, discussion_id)
        
        files_to_process = [file] if file else []
        evidence_briefing = await gather_evidence(
            report=analysis_report, 
            files=files_to_process,
            topic=topic,
            discussion_id=discussion_id
        )
        
        debate_team = await select_debate_team(
            analysis_report, jury_pool, special_agents, discussion_id
        )
        
        return debate_team
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An error occurred during orchestration: {e}")