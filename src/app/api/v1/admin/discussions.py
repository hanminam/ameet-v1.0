from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional

from langsmith import Client
from collections import defaultdict
from datetime import datetime

from app.api.v1.users import get_current_admin_user
from app.models.user import User as UserModel
from app.schemas.admin import DiscussionUsageResponse, TurnUsageDetail, AgentCostSummary, UsageSummaryResponse
from app.models.discussion import DiscussionLog
from app.schemas.discussion import DiscussionLogItem, DiscussionLogDetail
from app.models.discussion import User 
import re
from beanie.operators import In, RegEx

from datetime import datetime, timedelta
from calendar import monthrange
from beanie.operators import GTE, LT
from app.core.config import logger

router = APIRouter()

# --- 비용 계산을 위한 모델별 단가표 (USD per 1M tokens) ---
# ※ 참고: 이 단가는 예시이며, 실제 최신 단가는 각 LLM 공급자 사이트에서 확인해야 합니다.
TOKEN_PRICING_MAP = {
    # OpenAI
    "gpt-4o": {"input": 5.0, "output": 15.0},
    # Google
    "gemini-2.5-flash": {"input": 3.5, "output": 10.5},
    # Anthropic
    "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
    "claude-3-5-sonnet-20240620": {"input": 3.0, "output": 15.0},
}

def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    base_model = next((key for key in TOKEN_PRICING_MAP if model_name.startswith(key)), None)
    if not base_model: return 0.0
    pricing = TOKEN_PRICING_MAP[base_model]
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost

@router.get("/usage-summary", response_model=UsageSummaryResponse, summary="이번 달 토큰 사용량 요약 정보 조회")
async def get_usage_summary(admin_user: UserModel = Depends(get_current_admin_user)):
    try:
        today = datetime.utcnow()
        start_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days_in_month = monthrange(today.year, today.month)[1]
        end_of_month = start_of_month + timedelta(days=days_in_month)

        discussions_this_month = await DiscussionLog.find(
            GTE(DiscussionLog.created_at, start_of_month),
            LT(DiscussionLog.created_at, end_of_month)
        ).to_list()

        total_discussions_this_month = len(discussions_this_month)
        if total_discussions_this_month == 0:
            return UsageSummaryResponse(total_cost_this_month=0.0, total_discussions_this_month=0, average_cost_per_discussion=0.0)

        discussion_ids = [d.discussion_id for d in discussions_this_month]
        
        # Properly escape double quotes in the tags
        tags_to_check = [f'\\"discussion_id:{did}\\"' for did in discussion_ids]  # Escape quotes
        tags_list_str = f"[{', '.join(tags_to_check)}]"
        combined_filter = f"has_some(tags, {tags_list_str})"

        logger.debug(f"Filter string: {combined_filter}")
        
        client = Client()
        runs = list(client.list_runs(
            project_name="AMEET-MVP-v1.0",
            filter=combined_filter,
            run_type="llm"
        ))
        
        total_cost_this_month = 0.0
        for run in runs:
            model_name = run.extra.get("metadata", {}).get("model_name", "unknown")
            total_cost_this_month += calculate_cost(model_name, run.prompt_tokens, run.completion_tokens)

        average_cost = total_cost_this_month / total_discussions_this_month if total_discussions_this_month > 0 else 0

        return UsageSummaryResponse(
            total_cost_this_month=total_cost_this_month,
            total_discussions_this_month=total_discussions_this_month,
            average_cost_per_discussion=average_cost
        )
    except Exception as e:
        logger.error(f"Failed to get usage summary: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Failed to retrieve data: {e}")
    
@router.get(
    "/",
    response_model=List[DiscussionLogItem],
    summary="모든 토론 이력 목록 조회 (관리자용)"
)
async def list_all_discussions(
    status: Optional[str] = Query(None, description="토론 상태로 필터링"),
    search_by: str = Query("email", description="검색 기준 ('email' 또는 'name')"),
    search_term: Optional[str] = Query(None, description="검색어"),
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """
    모든 사용자의 토론 이력을 조회하고, 이메일, 사용자 이름, 상태로 필터링할 수 있습니다.
    """
    search_queries = []
    if status:
        search_queries.append(DiscussionLog.status == status)

    if search_term:
        if search_by == "email":
            # 이메일로 검색
            search_queries.append(RegEx(DiscussionLog.user_email, f".*{re.escape(search_term)}.*", "i"))
        elif search_by == "name":
            # 이름으로 사용자 검색
            users_found = await User.find(
                RegEx(User.name, f".*{re.escape(search_term)}.*", "i")
            ).to_list()
            
            user_emails = [user.email for user in users_found]
            
            if user_emails:
                # 찾은 이메일 목록으로 토론 검색
                search_queries.append(In(DiscussionLog.user_email, user_emails))
            else:
                return []

    # 모든 검색 조건을 함께 적용하여 쿼리 실행
    discussions = await DiscussionLog.find(*search_queries).sort(-DiscussionLog.created_at).to_list()
    
    # 1. 조회된 토론에서 사용자 이메일 목록을 추출합니다.
    if not discussions:
        return []
    
    discussion_user_emails = list({d.user_email for d in discussions})
    
    # 2. 해당 이메일을 가진 사용자 정보를 DB에서 조회합니다.
    users = await User.find(In(User.email, discussion_user_emails)).to_list()
    email_to_name_map = {user.email: user.name for user in users}
    
    # 3. 최종 응답 데이터를 조립합니다. (DiscussionLogItem 스키마에 맞게)
    response_data = [
        DiscussionLogItem(
            discussion_id=d.discussion_id,
            topic=d.topic,
            status=d.status,
            created_at=d.created_at,
            user_email=d.user_email,
            user_name=email_to_name_map.get(d.user_email, "N/A") # 사용자를 찾지 못할 경우 'N/A'
        ) for d in discussions
    ]
    
    return response_data

@router.get(
    "/{discussion_id}",
    response_model=DiscussionLogDetail,
    summary="특정 토론 상세 조회 (관리자용)"
)
async def get_any_discussion_detail(
    discussion_id: str,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """
    ID로 특정 토론의 상세 내용을 조회합니다.
    사용자 이름을 포함하여 반환합니다.
    """
    discussion = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    
    if not discussion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discussion not found.")
    
    # 사용자 이메일로 사용자 정보를 찾습니다.
    user = await User.find_one(User.email == discussion.user_email)
    user_name = user.name if user else "사용자 정보 없음"

    # DiscussionLogDetail 스키마에 맞게 응답 데이터를 구성하여 반환합니다.
    # model_dump()를 사용해 기존 discussion 데이터를 모두 포함시킵니다.
    return DiscussionLogDetail(
        **discussion.model_dump(),
        user_name=user_name
    )

@router.get(
    "/usage-summary",
    response_model=UsageSummaryResponse,
    summary="이번 달 토큰 사용량 요약 정보 조회"
)
async def get_usage_summary(admin_user: UserModel = Depends(get_current_admin_user)):
    """
    이번 달의 총 토론 수, 총 비용, 토론 당 평균 비용을 계산하여 반환합니다.
    """
    try:
        # 1. 이번 달의 시작일과 종료일 계산
        today = datetime.utcnow()
        start_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days_in_month = monthrange(today.year, today.month)[1]
        end_of_month = start_of_month + timedelta(days=days_in_month)

        # 2. DB에서 이번 달에 생성된 토론 목록 조회
        discussions_this_month = await DiscussionLog.find(
            GTE(DiscussionLog.created_at, start_of_month),
            LT(DiscussionLog.created_at, end_of_month)
        ).to_list()

        total_discussions_this_month = len(discussions_this_month)
        if total_discussions_this_month == 0:
            return UsageSummaryResponse(
                total_cost_this_month=0.0,
                total_discussions_this_month=0,
                average_cost_per_discussion=0.0
            )

        # 3. LangSmith에서 각 토론의 비용 집계
        client = Client()
        total_cost_this_month = 0.0
        
        for discussion in discussions_this_month:
            runs = list(client.list_runs(
                project_name="AMEET-MVP-v1.0",
                filter=f"has_tag('discussion_id:{discussion.discussion_id}')",
                run_type="llm"
            ))
            for run in runs:
                model_name = run.extra.get("metadata", {}).get("model_name", "unknown")
                total_cost_this_month += calculate_cost(model_name, run.prompt_tokens, run.completion_tokens)
        
        # 4. 평균 비용 계산
        average_cost = total_cost_this_month / total_discussions_this_month

        return UsageSummaryResponse(
            total_cost_this_month=total_cost_this_month,
            total_discussions_this_month=total_discussions_this_month,
            average_cost_per_discussion=average_cost
        )
    except Exception as e:
        logger.error(f"Failed to get usage summary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to retrieve data from LangSmith or DB: {e}"
        )