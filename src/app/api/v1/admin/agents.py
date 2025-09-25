from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional, Literal
from pydantic import BaseModel

from app.models.discussion import AgentSettings, AgentConfig
from app.api.v1.users import get_current_admin_user
from app.models.user import User as UserModel

router = APIRouter()

# --- API 요청/응답을 위한 Pydantic 스키마 정의 ---
class AgentCreateRequest(BaseModel):
    name: str
    agent_type: Literal["special", "expert"]
    config: AgentConfig

# --- API 엔드포인트 구현 ---

@router.get(
    "/",
    response_model=List[AgentSettings],
    summary="모든 에이전트의 최신 버전 목록 조회"
)
async def list_agents(
    agent_type: Optional[Literal["special", "expert"]] = None,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """
    DB에 저장된 모든 에이전트의 최신 버전 목록을 조회합니다.
    'agent_type' 쿼리 파라미터를 통해 'special' 또는 'expert' 에이전트만 필터링할 수 있습니다.
    'expert' 타입 조회 시 토론 참여 횟수(discussion_participation_count)가 많은 순으로 정렬됩니다.
    """
    match_stage = {}
    if agent_type:
        match_stage = {"agent_type": agent_type}

    if agent_type == "expert":
        sort_stage = {"$sort": {"discussion_participation_count": -1, "name": 1}}
    else:
        sort_stage = {"$sort": {"name": 1}}

    pipeline = [
        {"$match": match_stage} if match_stage else {"$match": {}},
        {"$sort": {"name": 1, "version": -1}},
        {"$group": {
            "_id": "$name",
            "latest_doc": {"$first": "$$ROOT"}
        }},
        {"$replaceRoot": {"newRoot": "$latest_doc"}},
        sort_stage
    ]
    
    # [수정] pipeline 리스트를 명시적인 'aggregation_pipeline' 키워드 인자로 전달합니다.
    agent_docs = await AgentSettings.aggregate(aggregation_pipeline=pipeline).to_list()
    return agent_docs

@router.post(
    "/",
    response_model=AgentSettings,
    status_code=status.HTTP_201_CREATED,
    summary="신규 에이전트 생성 (초안으로)"
)
async def create_agent(
    payload: AgentCreateRequest,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """
    새로운 에이전트를 'draft' 상태의 버전 1로 생성합니다.
    """
    existing_agent = await AgentSettings.find_one(AgentSettings.name == payload.name)
    if existing_agent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with name '{payload.name}' already exists."
        )
    
    new_agent = AgentSettings(
        name=payload.name,
        agent_type=payload.agent_type,
        version=1,
        status="draft",
        config=payload.config,
        last_modified_by=admin_user.email
    )
    await new_agent.insert()
    return new_agent

@router.put(
    "/{agent_name}",
    response_model=AgentSettings,
    summary="기존 에이전트 수정 (새 초안 생성)"
)
async def update_agent_as_draft(
    agent_name: str,
    config: AgentConfig,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """
    기존 에이전트의 설정을 변경하여 새로운 'draft' 버전을 생성합니다.
    기존의 active 버전은 그대로 유지됩니다.
    """
    latest_version_doc = await AgentSettings.find(
        AgentSettings.name == agent_name
    ).sort(-AgentSettings.version).first_or_none()

    if not latest_version_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    new_draft = AgentSettings(
        name=agent_name,
        version=latest_version_doc.version + 1,
        status="draft",
        config=config,
        last_modified_by=admin_user.email
    )
    
    await new_draft.insert()
    return new_draft

@router.post(
    "/{agent_name}/publish",
    response_model=AgentSettings,
    summary="초안을 활성 버전으로 게시"
)
async def publish_agent(
    agent_name: str,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """
    에이전트의 가장 최신 'draft' 버전을 'active' 상태로 변경합니다.
    기존 'active' 버전은 'archived'로 변경됩니다.
    """
    draft_to_publish = await AgentSettings.find_one(
        AgentSettings.name == agent_name,
        AgentSettings.status == "draft"
    )
    if not draft_to_publish:
        raise HTTPException(status_code=404, detail="No draft version found to publish.")

    current_active = await AgentSettings.find_one(
        AgentSettings.name == agent_name,
        AgentSettings.status == "active"
    )
    if current_active:
        current_active.status = "archived"
        await current_active.save()

    draft_to_publish.status = "active"
    draft_to_publish.last_modified_by = admin_user.email
    await draft_to_publish.save()
    
    return draft_to_publish

@router.delete(
    "/{agent_name}",
    response_model=AgentSettings,
    summary="에이전트 비활성화"
)
async def deactivate_agent(
    agent_name: str,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """
    현재 'active' 상태인 에이전트를 'archived' 상태로 변경하여 비활성화합니다.
    (Soft Delete)
    """
    agent_to_archive = await AgentSettings.find_one(
        AgentSettings.name == agent_name,
        AgentSettings.status == "active"
    )
    if not agent_to_archive:
        raise HTTPException(status_code=404, detail="Active agent not found.")
    
    agent_to_archive.status = "archived"
    agent_to_archive.last_modified_by = admin_user.email
    await agent_to_archive.save()
    return agent_to_archive