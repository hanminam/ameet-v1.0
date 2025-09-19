# src/app/api/v1/discussions.py

from asyncio.log import logger
from datetime import datetime
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Form, UploadFile, File
from typing import Dict, List, Optional

from app.services.orchestrator import get_active_agents_from_db, analyze_topic, gather_evidence, select_debate_team
from app.services.discussion_flow import execute_turn 
from app.schemas.orchestration import DebateTeam
from app.schemas.discussion import DiscussionLogItem, DiscussionLogDetail
from app.api.v1.users import get_current_user
from app.db import redis_client
from app.models.user import User as UserModel
from app.models.discussion import DiscussionLog

from pydantic import BaseModel
from app.services.report_generator import generate_report_background

class TurnRequest(BaseModel):
    user_vote: Optional[str] = None
    model_overrides: Optional[Dict[str, str]] = None

router = APIRouter(redirect_slashes=False)

# --- Endpoint 1: 토론 생성 및 오케스트레이션 ---
@router.post(
    "/",
    response_model=DebateTeam,
    status_code=status.HTTP_201_CREATED,
    summary="새로운 토론 생성 및 배심원단 구성"
)
async def create_discussion(
    topic: str = Form(...),
    file: Optional[UploadFile] = File(None),
    current_user: UserModel = Depends(get_current_user)
):
    """
    새로운 토론을 시작합니다.
    1. 토론 ID를 생성하고 DB에 초기 기록을 저장합니다.
    2. 오케스트레이션을 실행하여 토론팀을 구성합니다.
    3. 구성된 팀 정보를 반환하고, 토론은 'ready' 상태로 대기합니다.
    """
    discussion_log = None
    try:
        discussion_id = f"dscn_{uuid.uuid4()}"
        discussion_log = DiscussionLog(
            discussion_id=discussion_id,
            topic=topic,
            user_email=current_user.email,
            status="orchestrating" # 초기 상태: '팀 구성 중'
        )
        await discussion_log.insert()

        special_agents, jury_pool = await get_active_agents_from_db()
        analysis_report = await analyze_topic(topic, special_agents, discussion_id)
        files_to_process = [file] if file else []
        evidence_briefing = await gather_evidence(report=analysis_report, files=files_to_process, topic=topic, discussion_id=discussion_id)
        debate_team = await select_debate_team(analysis_report, jury_pool, special_agents, discussion_id)

        # 구성된 팀 정보를 DB에 저장합니다.
        discussion_log.participants = [
            debate_team.judge.model_dump(),
            *[agent.model_dump() for agent in debate_team.jury]
        ]

        # 수집된 증거 자료집을 Pydantic 모델에서 dict로 변환하여 DB에 저장합니다.
        discussion_log.evidence_briefing = evidence_briefing.model_dump()
        
        # 오케스트레이션 완료 후 상태를 'ready'로 변경
        discussion_log.status = "ready"
        await discussion_log.save()
        
        return debate_team
        
    except Exception as e:
        if discussion_log:
            discussion_log.status = "failed"
            await discussion_log.save()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An error occurred during orchestration: {e}")


# --- Endpoint 2: 토론 단계(Turn) 실행 ---
@router.post(
    "/{discussion_id}/turns",
    status_code=status.HTTP_202_ACCEPTED,
    summary="다음 토론 단계 실행"
)
async def execute_discussion_turn(
    discussion_id: str,
    turn_request: TurnRequest, # Pydantic 모델로 user_vote 받기
    background_tasks: BackgroundTasks,
    current_user: UserModel = Depends(get_current_user)
):
    """
    특정 토론의 다음 단계를 백그라운드에서 실행합니다.
    사용자가 '토론 시작하기', '다음 라운드 진행' 버튼을 눌렀을 때 호출됩니다.
    """
    # 1. DB에서 해당 토론 기록을 찾습니다.
    discussion_log = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    
    # 2. 토론 기록이 없거나, 요청한 사용자가 소유자가 아닌 경우 오류를 반환합니다.
    if not discussion_log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discussion not found.")
    if discussion_log.user_email != current_user.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this discussion.")

    # 3. 토론이 다음 단계를 실행할 수 있는 상태인지 확인합니다.
    # ('ready', 'turn_complete', 'waiting_for_vote') 상태일 때만 진행 가능합니다.
    if discussion_log.status not in ["ready", "turn_complete", "waiting_for_vote"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, 
            detail=f"Cannot start a new turn. Current status is '{discussion_log.status}'."
        )

    # 4. 토론 상태를 'turn_inprogress'(턴 진행 중)으로 변경하고 DB에 즉시 저장합니다.
    discussion_log.status = "turn_inprogress"
    await discussion_log.save()

    # 5. 실제 토론을 진행할 함수를 백그라운드 작업으로 추가합니다.
    # 이 작업은 아래 return 문이 실행된 후에 비동기적으로 처리됩니다.
    # 백그라운드 작업에 user_vote 전달
    background_tasks.add_task(
        execute_turn, 
        discussion_log, 
        turn_request.user_vote,
        turn_request.model_overrides
    )

    # 6. 클라이언트에게 작업이 백그라운드에서 시작되었음을 즉시 알립니다.
    return {"message": "Discussion turn execution started in the background."}

@router.get(
    "/",
    response_model=List[DiscussionLogItem],
    summary="나의 토론 이력 목록 조회"
)
async def get_my_discussions(
    current_user: UserModel = Depends(get_current_user)
):
    """
    현재 로그인한 사용자의 모든 토론 이력 목록을 최신순으로 반환합니다.
    """
    discussions = await DiscussionLog.find(
        DiscussionLog.user_email == current_user.email
    ).sort(-DiscussionLog.created_at).to_list()
    
    return discussions

@router.get(
    "/{discussion_id}",
    response_model=DiscussionLogDetail,
    summary="특정 토론 상세 조회"
)
async def get_discussion_detail(
    discussion_id: str,
    current_user: UserModel = Depends(get_current_user)
):
    """
    특정 토론의 상세 내용을 조회합니다.
    자신이 생성한 토론이 아닐 경우 접근이 거부됩니다. 
    """
    discussion = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    
    if not discussion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discussion not found.")
        
    if discussion.user_email != current_user.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this discussion.")
        
    return discussion

# 토론 종료 (보고서 생성 없음)
@router.post(
    "/{discussion_id}/archive",
    status_code=status.HTTP_200_OK,
    summary="토론을 종료하고 상태만 변경 (보고서 생성 없음)"
)
async def archive_discussion(
    discussion_id: str,
    current_user: UserModel = Depends(get_current_user)
):
    """
    사용자가 '보고서 없이 종료'를 선택했을 때 호출됩니다.
    1. 토론 상태를 'completed'로 변경하고 종료 시간을 기록합니다.
    2. 보고서 생성 파이프라인은 실행하지 않습니다.
    """
    # 1. DB에서 해당 토론 기록을 찾습니다.
    discussion_log = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    
    # 2. 유효성 검사 (토론 존재 여부, 소유자 확인)
    if not discussion_log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discussion not found.")
    if discussion_log.user_email != current_user.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized.")

    # 3. 상태를 'completed'로 변경하고 완료 시간 기록
    discussion_log.status = "completed"
    discussion_log.completed_at = datetime.utcnow()
    await discussion_log.save()
    
    # 4. 클라이언트에게 작업이 완료되었음을 알림
    return {"message": "Discussion has been successfully archived without generating a report."}

# 토론 종료 및 보고서 생성 시작 ---
@router.post(
    "/{discussion_id}/complete",
    status_code=status.HTTP_202_ACCEPTED,
    summary="토론을 종료하고 보고서 생성을 시작"
)
async def complete_discussion_and_generate_report(
    discussion_id: str,
    background_tasks: BackgroundTasks,
    current_user: UserModel = Depends(get_current_user)
):
    """
    사용자가 토론 종료를 요청했을 때 호출됩니다.
    1. 토론 상태를 'report_generating'으로 변경합니다.
    2. 실제 보고서 생성 및 PDF 저장은 백그라운드 작업으로 위임합니다.
    """
    # 1. DB에서 해당 토론 기록을 찾습니다.
    discussion_log = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    
    # 2. 유효성 검사 (토론 존재 여부, 소유자 확인)
    if not discussion_log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discussion not found.")
    if discussion_log.user_email != current_user.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized.")

    # 3. 상태를 'report_generating'으로 변경하고 완료 시간 기록
    discussion_log.status = "report_generating"
    discussion_log.completed_at = datetime.utcnow()
    await discussion_log.save()

    # 4. 보고서 생성 파이프라인 함수를 백그라운드 작업으로 등록
    background_tasks.add_task(generate_report_background, discussion_id)
    
    # 5. 클라이언트에게 작업이 접수되었음을 즉시 알림
    return {"message": "Discussion completed. Report generation has started in the background."}