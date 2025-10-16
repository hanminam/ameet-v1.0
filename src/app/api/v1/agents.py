# src/app/api/v1/agents.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from app.models.discussion import AgentSettings
from app.api.v1.users import get_current_user
from app.models.user import User as UserModel
from app.core.config import settings, logger
from app import db

router = APIRouter()

@router.get(
    "/search",
    response_model=List[AgentSettings],
    summary="에이전트 검색 (일반 사용자용)"
)
async def search_agents(
    name_like: Optional[str] = Query(None, description="에이전트 이름에 포함될 검색어"),
    current_user: UserModel = Depends(get_current_user)
):
    """
    일반 사용자가 expert 타입의 에이전트를 검색합니다.
    토론에 추가할 전문가를 찾을 때 사용합니다.

    - 검색 대상: agent_type='expert', status='active'인 에이전트
    - 정렬: discussion_participation_count 내림차순 (인기순)
    """
    pipeline = []
    match_query = {
        "agent_type": "expert",
        "status": "active"
    }

    if name_like:
        match_query["name"] = {"$regex": name_like, "$options": "i"}

    pipeline.extend([
        {"$match": match_query},
        {"$sort": {"name": 1, "version": -1}},
        {"$group": {"_id": "$name", "latest_doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$latest_doc"}},
        {"$sort": {"discussion_participation_count": -1, "name": 1}},
        {"$limit": 20}  # 최대 20개까지만 반환
    ])

    try:
        if not db.mongo_client:
            raise HTTPException(status_code=503, detail="Database is not available.")

        db_name = settings.MONGO_DB_URL.split("/")[-1].split("?")[0]
        collection = db.mongo_client[db_name]["agents"]

        logger.info(f"--- [AGENT SEARCH] User '{current_user.email}' searching for: '{name_like}' ---")

        cursor = collection.aggregate(pipeline)
        agent_docs_raw = await cursor.to_list(length=None)

        logger.info(f"--- [AGENT SEARCH] Found {len(agent_docs_raw)} agents ---")

        agent_docs = [AgentSettings.model_validate(doc) for doc in agent_docs_raw]
        return agent_docs

    except Exception as e:
        logger.error(
            f"--- [AGENT SEARCH ERROR] Failed for user '{current_user.email}'.",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search agents: {str(e)}"
        )
