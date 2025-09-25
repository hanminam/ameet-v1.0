# src/app/api/v1/admin/agents.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional, Literal
from pydantic import BaseModel

from app.models.discussion import AgentSettings, AgentConfig
from app.api.v1.users import get_current_admin_user
from app.models.user import User as UserModel

router = APIRouter()

# --- API 요청/응답을 위한 Pydantic 스키마 정의 ---
class AgentCreateRequest(BaseModel):
 
   name: str
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
    name_like: Optional[str] = Query(None, description="에이전트 이름에 포함될 검색어"),
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """
    DB에 저장된 모든 에이전트의 최신 버전 목록을 조회합니다.
    name_like 파라미터를 통해 expert 에이전트의 이름 검색을 지원합니다.
    """
    pipeline = []
    
    match_query = {}
    if agent_type:
        match_query["agent_type"] = agent_type
    
    if agent_type == "expert" and name_like:
        match_query["name"] = {"$regex": name_like, "$options": "i"}

    if match_query:
        pipeline.append({"$match": match_query})

    pipeline.extend([
        {"$sort": {"name": 1, "version": -1}},
        {"$group": {
            "_id": "$name",
            "latest_doc": {"$first": "$$ROOT"}
        }},
        {"$replaceRoot": {"newRoot": "$latest_doc"}}
    ])

    if agent_type == "expert":
        pipeline.append({"$sort": {"discussion_participation_count": -1, "name": 1}})
    else:
        pipeline.append({"$sort": {"name": 1}})
    
    # [원상 복구] Beanie의 표준적인 aggregation 사용법으로 되돌립니다.
    # 단일 워커 환경에서는 이 코드가 정상적으로 동작합니다.
    agent_docs = await AgentSettings.aggregate(pipeline).to_list()
    
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
    existing_agent = await AgentSettings.find_one(AgentSettings.name == payload.name)
    if existing_agent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with name '{payload.name}' already exists."
        )
    
    new_agent = AgentSettings(
        name=payload.name,
        agent_type="expert",
        version=1,
        status="active",
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