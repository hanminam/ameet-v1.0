# src/app/api/v1/discussion.py

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File, BackgroundTasks
from app.services.discussion_flow import run_discussion_flow

from app.services.orchestrator import (
    get_active_agents_from_db, # DB 조회 함수 임포트
    analyze_topic,
    gather_evidence,
    select_debate_team
)
from app.schemas.orchestration import DebateTeam
from app.api.v1.users import get_current_user
from app.models.user import User as UserModel
from app.models.discussion import DiscussionLog

router = APIRouter()

@router.post("/orchestrate", response_model=DebateTeam)
async def run_orchestration_pipeline(
    background_tasks: BackgroundTasks,
    topic: str = Form(...),
    file: Optional[UploadFile] = File(None),
    current_user: UserModel = Depends(get_current_user)
):
    discussion_log = None # discussion_log 변수 초기화
    try:
        # 1. 고유한 토론 ID 생성 및 DB에 초기 기록 생성
        discussion_id = f"dscn_{uuid.uuid4()}"
        
        discussion_log = DiscussionLog(
            discussion_id=discussion_id,
            topic=topic,
            user_email=current_user.email,
            status="processing" # 초기 상태는 '진행 중'
        )
        await discussion_log.insert()
        print(f"--- [History] Discussion log created with ID: {discussion_id} ---")

        # 2. 기존 오케스트레이션 로직 수행
        special_agents, jury_pool = await get_active_agents_from_db()        
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
        
        # 실제 토론 진행을 백그라운드 작업으로 추가합니다.
        # 이 작업은 API가 응답을 반환한 후에 실행됩니다.
        background_tasks.add_task(
            run_discussion_flow, 
            discussion_id, 
            debate_team, 
            topic
        )
        
        return debate_team
        
    except Exception as e:
        # 3. 오케스트레이션 중 오류 발생 시, DB 기록의 상태를 'failed'로 업데이트
        if discussion_log:
            discussion_log.status = "failed"
            await discussion_log.save()
            print(f"--- [History] Discussion log {discussion_log.discussion_id} status updated to 'failed'. ---")
            
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An error occurred during orchestration: {e}")