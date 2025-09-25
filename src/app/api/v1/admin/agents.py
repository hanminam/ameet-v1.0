# src/app/api/v1/admin/agents.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional, Literal, Dict
from pydantic import BaseModel

from app.models.discussion import AgentSettings, AgentConfig
from app.api.v1.users import get_current_admin_user
from app.models.user import User as UserModel

from app.core.config import settings
from app import db 

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
    
    # [최종 수정] Beanie 모델의 메서드 대신, 초기화가 보장된 db.mongo_client를 직접 사용합니다.
    try:
        if not db.mongo_client:
            raise HTTPException(status_code=503, detail="Database is not available.")

        # 1. 데이터베이스 이름을 가져옵니다.
        db_name = settings.MONGO_DB_URL.split("/")[-1].split("?")[0]
        
        # 2. mongo_client에서 직접 데이터베이스와 컬렉션을 선택합니다.
        collection = db.mongo_client[db_name]["agents"]
        
        # 3. 컬렉션 객체에 직접 aggregation을 실행합니다.
        cursor = collection.aggregate(pipeline)
        
        # 4. motor cursor의 to_list를 사용하여 결과를 가져옵니다.
        agent_docs_raw = await cursor.to_list(length=None)
        
        # 5. Raw dictionary를 Pydantic 모델로 파싱하여 응답 형식을 맞춥니다.
        agent_docs = [AgentSettings.model_validate(doc) for doc in agent_docs_raw]
        return agent_docs
        
    except Exception as e:
        # DB 쿼리 중 발생할 수 있는 예외를 처리합니다.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve agents from database: {str(e)}"
        )

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
    summary="기존 에이전트 수정" # [수정] "(새 초안 생성)" 문구 삭제
)
async def update_agent( # [수정] 함수 이름 변경
    agent_name: str,
    config: AgentConfig,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    current_active_doc = await AgentSettings.find_one(
        AgentSettings.name == agent_name,
        AgentSettings.status == "active"
    )

    if not current_active_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active agent to update not found")
    
    # 기존 버전을 archived로 변경
    current_active_doc.status = "archived"
    await current_active_doc.save()

    # 수정된 내용으로 새 버전을 active 상태로 생성
    new_active_version = AgentSettings(
        name=agent_name,
        agent_type=current_active_doc.agent_type,
        version=current_active_doc.version + 1,
        status="active", # [수정] 수정된 버전도 즉시 'active'
        config=config,
        last_modified_by=admin_user.email
    )
    
    await new_active_version.insert()

    return new_active_version

@router.delete(
    "/{agent_name}",
    response_model=Dict[str, str], # 응답 모델을 간단한 딕셔너리로 변경
    summary="에이전트 영구 삭제"
)
async def delete_agent( # 함수 이름 변경
    agent_name: str,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    # 3. 해당 이름을 가진 모든 버전의 문서를 DB에서 영구 삭제
    delete_result = await AgentSettings.find(
        AgentSettings.name == agent_name
    ).delete()

    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Agent not found to delete.")
    
    return {"message": f"Agent '{agent_name}' was permanently deleted."}