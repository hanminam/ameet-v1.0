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
from app.models.discussion import DiscussionLog, User

from pydantic import BaseModel
from app.services.report_generator import generate_report_background

class TurnRequest(BaseModel):
    user_vote: Optional[str] = None
    model_overrides: Optional[Dict[str, str]] = None

router = APIRouter(redirect_slashes=False)

# --- 백그라운드에서 실행될 오케스트레이션 함수 ---
async def run_orchestration_background(discussion_id: str, topic: str, file: Optional[UploadFile], user_email: str):
    """백그라운드에서 오케스트레이션을 실행하는 함수"""
    discussion_log = None
    try:
        discussion_log = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
        if not discussion_log:
            return

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

    except Exception as e:
        if discussion_log:
            discussion_log.status = "failed"
            await discussion_log.save()
        import traceback
        traceback.print_exc()

# --- Endpoint 1: 토론 생성 및 오케스트레이션 ---
@router.post(
    "/",
    status_code=status.HTTP_202_ACCEPTED,
    summary="새로운 토론 생성 및 배심원단 구성"
)
async def create_discussion(
    background_tasks: BackgroundTasks,
    topic: str = Form(...),
    file: Optional[UploadFile] = File(None),
    current_user: UserModel = Depends(get_current_user)
):
    """
    새로운 토론을 시작합니다.
    1. 토론 ID를 즉시 생성하여 반환합니다.
    2. 오케스트레이션은 백그라운드에서 실행됩니다.
    3. 클라이언트는 /progress API를 폴링하여 진행 상황을 확인합니다.
    """
    try:
        discussion_id = f"dscn_{uuid.uuid4()}"
        discussion_log = DiscussionLog(
            discussion_id=discussion_id,
            topic=topic,
            user_email=current_user.email,
            status="orchestrating"
        )
        await discussion_log.insert()

        # 백그라운드 작업으로 오케스트레이션 실행
        background_tasks.add_task(
            run_orchestration_background,
            discussion_id,
            topic,
            file,
            current_user.email
        )

        # 즉시 discussion_id 반환
        return {"discussion_id": discussion_id, "status": "orchestrating"}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to create discussion: {e}")


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
    
    # 사용자 이름을 채워주기 위한 로직 추가
    user = await User.find_one(User.email == current_user.email)
    user_name = user.name if user else "N/A"

    response_data = []
    for d in discussions:
        item = d.model_dump()
        item["user_name"] = user_name
        response_data.append(DiscussionLogItem(**item))

    return response_data

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
    
    # 1. 토론 로그의 이메일로 사용자 정보를 찾습니다.
    user = await User.find_one(User.email == discussion.user_email)
    user_name = user.name if user else "사용자 정보 없음"

    # 2. Pydantic 스키마에 맞게 응답 데이터를 구성하여 반환합니다.
    #    discussion.model_dump()를 사용해 기존 discussion 데이터를 모두 포함시키고,
    #    user_name 필드를 추가합니다.
    response_data = discussion.model_dump()
    
    response_data["user_name"] = user_name
    
    return DiscussionLogDetail(**response_data)

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

# --- 진행 상황 조회 API ---
@router.get(
    "/{discussion_id}/progress",
    summary="오케스트레이션 진행 상황 조회"
)
async def get_orchestration_progress(
    discussion_id: str,
    current_user: UserModel = Depends(get_current_user)
):
    """
    Redis에 저장된 오케스트레이션 진행 상황을 조회합니다.
    프론트엔드에서 폴링하여 사용자에게 실시간 피드백을 제공합니다.
    """
    import json
    from app import db

    try:
        progress_json = await db.redis_client.get(f"orchestration_progress:{discussion_id}")

        if not progress_json:
            return {
                "stage": "대기 중",
                "message": "진행 상황 정보를 불러오는 중입니다...",
                "progress": 0
            }

        progress_data = json.loads(progress_json)
        return progress_data

    except Exception as e:
        return {
            "stage": "오류",
            "message": f"진행 상황을 가져올 수 없습니다: {str(e)}",
            "progress": 0
        }