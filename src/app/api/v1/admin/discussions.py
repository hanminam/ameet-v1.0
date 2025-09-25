from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional

from langsmith import Client
from collections import defaultdict
from datetime import datetime

from app.api.v1.users import get_current_admin_user
from app.models.user import User as UserModel
from app.schemas.admin import DiscussionUsageResponse, TurnUsageDetail, AgentCostSummary
from app.models.discussion import DiscussionLog
from app.schemas.discussion import DiscussionLogItem, DiscussionLogDetail
from app.models.discussion import User 
import re
from beanie.operators import In, RegEx

router = APIRouter()

# --- 비용 계산을 위한 모델별 단가표 (USD per 1M tokens) ---
# ※ 참고: 이 단가는 예시이며, 실제 최신 단가는 각 LLM 공급자 사이트에서 확인해야 합니다.
TOKEN_PRICING_MAP = {
    # OpenAI
    "gpt-4o": {"input": 5.0, "output": 15.0},
    # Google
    "gemini-1.5-pro": {"input": 3.5, "output": 10.5},
    "gemini-1.5-flash": {"input": 0.35, "output": 1.05},
    # Anthropic
    "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
    "claude-3-5-sonnet-20240620": {"input": 3.0, "output": 15.0},
}

def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """모델 이름과 토큰 수를 기반으로 비용을 계산합니다."""
    # model_name에 버전이 포함된 경우(예: gpt-4o-2024-05-13) base model 이름만 추출
    base_model = next((key for key in TOKEN_PRICING_MAP if model_name.startswith(key)), None)
    
    if not base_model:
        return 0.0

    pricing = TOKEN_PRICING_MAP[base_model]
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost

@router.get(
    "/{discussion_id}/usage",
    response_model=DiscussionUsageResponse,
    summary="특정 토론의 토큰/비용 사용량 상세 조회"
)
async def get_discussion_usage_details(
    discussion_id: str,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """
    LangSmith에서 특정 discussion_id 태그를 가진 모든 LLM 호출 기록을 가져와
    상세 사용 내역을 분석하여 반환합니다.
    """
    try:
        client = Client()
        # 1. LangSmith에서 해당 discussion_id 태그를 가진 모든 LLM 실행 기록 조회
        runs = list(client.list_runs(
            project_name="AMEET-v1.0",
            filter=f"has_tag('discussion_id:{discussion_id}')",
            run_type="llm"
        ))
        
        if not runs:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usage data not found for this discussion ID.")

        # 2. 조회된 기록을 순회하며 상세 내역(turn_details) 생성
        turn_details = []
        agent_cost_agg = defaultdict(lambda: {"tokens": 0, "cost": 0.0})

        for run in sorted(runs, key=lambda r: r.start_time):
            model_name = run.extra.get("metadata", {}).get("model_name", "unknown")
            input_tokens = run.prompt_tokens
            output_tokens = run.completion_tokens
            total_tokens = run.total_tokens
            cost = calculate_cost(model_name, input_tokens, output_tokens)
            
            # run.name은 보통 'ChatGoogleGenerativeAI' 등으로 기록되므로, 더 의미있는 이름을 찾아야 함
            # 예시: 부모 run의 이름을 가져오는 로직 (추후 고도화 가능)
            turn_name = run.name 

            turn_details.append(TurnUsageDetail(
                turn_name=turn_name,
                model_name=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
                latency_ms=(run.end_time - run.start_time).total_seconds() * 1000,
                start_time=run.start_time
            ))
            
            agent_cost_agg[turn_name]["tokens"] += total_tokens
            agent_cost_agg[turn_name]["cost"] += cost

        # 3. 에이전트별 비용/토큰 요약 (agent_summary) 생성
        agent_summary = [
            AgentCostSummary(
                agent_name=name,
                total_cost_usd=data["cost"],
                total_tokens=data["tokens"]
            ) for name, data in agent_cost_agg.items()
        ]

        # 4. 토론의 메타데이터(주제, 사용자 이메일)를 우리 DB에서 조회
        # discussion_id 형식이 dscn_... 이므로 beanie가 인식할 수 있게 변환 필요
        mongo_discussion_id = discussion_id.replace("dscn_", "")
        discussion_log = await DiscussionLog.get(mongo_discussion_id)
        
        topic = discussion_log.topic if discussion_log else "Topic not found"
        user_email = discussion_log.user_email if discussion_log else "User not found"

        # 5. 최종 응답 데이터 조립
        total_cost = sum(t.cost_usd for t in turn_details)
        total_tokens = sum(t.total_tokens for t in turn_details)
        start_time = min(t.start_time for t in turn_details)
        end_time = max(t.start_time for t in turn_details) # end_time이 없는 경우 start_time으로 대체
        
        return DiscussionUsageResponse(
            discussion_id=discussion_id,
            topic=topic,
            user_email=user_email,
            total_cost_usd=total_cost,
            total_tokens=total_tokens,
            start_time=start_time,
            duration_seconds=(end_time - start_time).total_seconds(),
            turn_details=turn_details,
            agent_summary=agent_summary
        )

    except Exception as e:
        # LangSmith API 키가 잘못되었거나 네트워크 오류 발생 시
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to retrieve data from LangSmith: {e}"
        )
    
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
    return discussions

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
    ID로 특정 토론의 상세 내용을 조회합니다. (소유자 제한 없음)
    """
    discussion = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    
    if not discussion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discussion not found.")
        
    return discussion