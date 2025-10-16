# src/app/api/v1/agents.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from pydantic import BaseModel
from app.models.discussion import AgentSettings, AgentConfig
from app.api.v1.users import get_current_user
from app.models.user import User as UserModel
from app.core.config import settings, logger
from app import db

router = APIRouter()

# orchestrator.py의 아이콘 맵 재사용
ICON_MAP = {
    # 역할/직업
    "재판관": "🧑", "분석가": "📊", "경제": "🌍", "산업": "🏭", "재무": "💹",
    "트렌드": "📈", "비판": "🤔", "전문가": "🧑", "미시": "🛒", "미래학자": "🔭",
    "물리학": "⚛️", "양자": "🌀", "의학": "⚕️", "심리학": "🧠", "뇌과학": "⚡️",
    "문학": "✍️", "역사": "🏛️", "생물학": "🧬", "법의학": "🔬", "법률": "⚖️",
    "회계": "🧾", "인사": "👥", "인류학": "🗿", "IT": "💻", "개발": "👨‍💻",
    # 고유명사/인물
    "버핏": "👴", "린치": "👨‍💼", "잡스": "💡", "머스크": "🚀", "베이조스": "📦",
    "웰치": "🏆", "아인슈타인": "🌌",
    # 기타 키워드
    "선정": "📋", "분석": "🔎", "자동차": "🚗", "기술": "⚙️", "환경": "🌱"
}
DEFAULT_ICON = "🧑"

def _get_icon_for_agent(agent_name: str) -> str:
    """
    에이전트 이름을 기반으로 가장 적합한 아이콘을 반환합니다.
    orchestrator.py의 로직과 동일합니다.
    """
    # 이름에서 가장 길게 일치하는 키워드 찾기
    name_matches = [keyword for keyword in ICON_MAP if keyword in agent_name]
    if name_matches:
        best_match = max(name_matches, key=len)
        return ICON_MAP[best_match]

    return DEFAULT_ICON

class CreateAgentRequest(BaseModel):
    agent_name: str

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

async def _get_default_agent_prompt() -> str:
    """
    DB에서 default_agent_prompt를 조회합니다.
    admin/settings.py의 로직과 동일하게 처리합니다.
    """
    try:
        db_name = settings.MONGO_DB_URL.split("/")[-1].split("?")[0]
        collection = db.mongo_client[db_name]["system_settings"]
        setting_data = await collection.find_one({"key": "default_agent_prompt"})

        if not setting_data:
            # Fallback: 기본값 반환
            fallback_prompt = (
                "당신의 역할은 '{role}'이며 지정된 역할 관점에서 말하세요.\n"
                "당신의 역할에 맞는 대화스타일을 사용하세요.\n"
                "토의 규칙을 숙지하고 토론의 목표를 달성하기 위해 제시된 의견들을 바탕으로 보완의견을 제시하거나, 주장을 강화,철회,수정 하세요.\n"
                "모든 의견은 논리적이고 일관성이 있어야 하며 신뢰할 수 있는 출처에 기반해야하고 자세하게 답변하여야 합니다.\n"
                "사용자가 질문한 언어로 답변하여야 합니다."
            )
            logger.info("--- [GET DEFAULT PROMPT] Using fallback prompt ---")
            return fallback_prompt

        logger.info("--- [GET DEFAULT PROMPT] Retrieved from DB ---")
        return setting_data.get("value", "")

    except Exception as e:
        logger.error(f"--- [GET DEFAULT PROMPT ERROR] {e} ---", exc_info=True)
        # 오류 발생 시 기본값 반환
        return (
            "당신의 역할은 '{role}'이며 지정된 역할 관점에서 말하세요.\n"
            "당신의 역할에 맞는 대화스타일을 사용하세요.\n"
            "토의 규칙을 숙지하고 토론의 목표를 달성하기 위해 제시된 의견들을 바탕으로 보완의견을 제시하거나, 주장을 강화,철회,수정 하세요.\n"
            "모든 의견은 논리적이고 일관성이 있어야 하며 신뢰할 수 있는 출처에 기반해야하고 자세하게 답변하여야 합니다.\n"
            "사용자가 질문한 언어로 답변하여야 합니다."
        )

@router.post(
    "/",
    response_model=AgentSettings,
    status_code=status.HTTP_201_CREATED,
    summary="신규 에이전트 생성 (일반 사용자용)"
)
async def create_agent_for_user(
    request: CreateAgentRequest,
    current_user: UserModel = Depends(get_current_user)
):
    """
    일반 사용자가 새로운 expert 에이전트를 생성합니다.
    토론에 추가할 전문가를 직접 만들 때 사용합니다.

    - 이름만 입력하면 아이콘과 프롬프트는 자동 생성됩니다.
    - 중복된 이름은 허용되지 않습니다.
    - 자동으로 active 상태로 생성됩니다.
    """
    agent_name = request.agent_name.strip()

    if not agent_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent name is required."
        )

    # 1. 중복 체크
    existing_agent = await AgentSettings.find_one(AgentSettings.name == agent_name)
    if existing_agent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with name '{agent_name}' already exists."
        )

    # 2. 기본 프롬프트 템플릿 가져오기
    prompt_template = await _get_default_agent_prompt()
    agent_prompt = prompt_template.format(role=agent_name)

    # 3. 아이콘 자동 생성
    selected_icon = _get_icon_for_agent(agent_name)

    # 4. 에이전트 생성
    new_agent_config = AgentConfig(
        prompt=agent_prompt,
        model="gemini-2.5-flash",
        temperature=0.3,
        icon=selected_icon
    )

    new_agent = AgentSettings(
        name=agent_name,
        agent_type="expert",
        version=1,
        status="active",
        config=new_agent_config,
        last_modified_by=current_user.email,
        discussion_participation_count=0
    )

    await new_agent.insert()

    logger.info(f"--- [CREATE AGENT] User '{current_user.email}' created agent '{agent_name}' (Icon: {selected_icon}) ---")

    return new_agent
