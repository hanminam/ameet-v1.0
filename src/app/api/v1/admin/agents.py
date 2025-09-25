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
    # 프론트엔드에서 agent_type을 보내지 않아도 되도록 Optional로 변경하고 기본값을 expert로 설정
    agent_type: Literal["special", "expert"] = "expert" 
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
    DB 집계(aggregate) 대신 Python으로 직접 데이터를 처리하여 안정성을 확보합니다.
    """
    find_query = {"status": "active"}
    if agent_type:
        find_query["agent_type"] = agent_type
    
    all_active_agents = await AgentSettings.find(find_query).to_list()

    latest_agents_map = {}
    for agent in all_active_agents:
        if (agent.name not in latest_agents_map) or (agent.version > latest_agents_map[agent.name].version):
            latest_agents_map[agent.name] = agent
            
    latest_agents_list = list(latest_agents_map.values())

    if agent_type == "expert":
        latest_agents_list.sort(key=lambda x: (-x.discussion_participation_count, x.name))
    else:
        latest_agents_list.sort(key=lambda x: x.name)

    return latest_agents_list

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
        agent_type="expert", # [수정] 항상 'expert' 타입으로 생성되도록 강제
        version=1,
        status="draft",
        config=payload.config,
        last_modified_by=admin_user.email
    )
    await new_agent.insert()
    return new_agent

# (이하 다른 엔드포인트들은 변경되지 않았습니다)
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