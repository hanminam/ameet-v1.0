# src/app/services/discussion_flow.py

import asyncio
import json
from typing import Dict, List, Literal, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai import ChatVertexAI
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from app.tools.search import perform_web_search_async, web_search_tool
from datetime import datetime
from langchain_core.messages import BaseMessage
from app.schemas.orchestration import AgentDetail

from pydantic import BaseModel, ValidationError

from app import db
from app.db import redis_client

from app.schemas.orchestration import DebateTeam
from app.models.discussion import AgentSettings, DiscussionLog
from app.services.utility_agents import run_snr_agent, run_verifier_agent
from app.core.config import logger

from app.schemas.orchestration import AgentDetail # AgentDetail 스키마 추가
from app.schemas.discussion import VoteContent
from app.schemas.discussion import InteractionAnalysisResult
import re

# 에이전트 및 도구 실행을 위한 LangChain 모듈 임포트
from langchain.agents import AgentExecutor, create_tool_calling_agent
from app.tools.search import available_tools

# ReAct 패턴을 적용한 강력한 시스템 레벨 도구 사용 규칙 정의
SYSTEM_TOOL_INSTRUCTION_BLOCK = """
---
### Tools Guide (VERY IMPORTANT)

You have access to a `web_search` tool. Your decision to use it must follow a strict 2-step process:

**Step 1: Evaluate Provided Information**
First, thoroughly review the "[중앙 집중식 웹 검색 결과]" and "[참고 자료]" provided in the prompt. This is the baseline information for the current turn.

**Step 2: Justify and Execute Supplemental Search (If Necessary)**
You are authorized to use the `web_search` tool **ONLY IF** the provided information is insufficient for you to perform your specific role as an expert.

-   **Justification (Internal Thought):** Before calling the tool, you must internally reason why a supplemental search is critical. For example: "As a Financial Analyst, the general overview of robotaxis is not enough. I need specific, recent financial data."
-   **Execution:** If justified, perform **one, highly-specific** search to acquire the missing information. Do NOT repeat the general search that was already provided.

**CRITICAL RULES:**
-   **DO NOT** use the `web_search` tool if the provided information is sufficient.
-   Your final answer MUST be a complete, natural language response, not a JSON object.
-   Do not mention your tool usage in your final answer. Integrate the findings naturally into your argument.
---
"""

# 입장 변화 분석 결과 Pydantic 모델
class StanceAnalysis(BaseModel):
    change: Literal['유지', '강화', '수정', '약화']
    reason: str

# 검색 코디네이터를 호출하는 새로운 내부 함수
async def _get_search_query(discussion_log: DiscussionLog, user_vote: Optional[str]) -> Optional[str]:
    try:
        coordinator_setting = await AgentSettings.find_one(
            AgentSettings.name == "Search Coordinator", AgentSettings.status == "active"
        )
        if not coordinator_setting:
            logger.warning("!!! 'Search Coordinator' 에이전트를 찾을 수 없습니다. 중앙 검색을 건너뜁니다.")
            return None

        history_str = "\n\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript])
        
        human_prompt = (
            f"토론 주제: {discussion_log.topic}\n\n"
            f"지금까지의 토론 내용:\n{history_str}\n\n"
            f"사용자의 다음 라운드 지시사항: '{user_vote}'\n\n"
            "위 내용을 바탕으로, 다음 토론에 가장 도움이 될 단 하나의 웹 검색어를 생성해주세요."
        )

        llm = ChatGoogleGenerativeAI(model=coordinator_setting.config.model)
        prompt = ChatPromptTemplate.from_messages([
            ("system", coordinator_setting.config.prompt),
            ("human", "{input}")
        ])
        chain = prompt | llm
        
        response = await chain.ainvoke(
            {"input": human_prompt},
            config={"tags": [f"discussion_id:{discussion_log.discussion_id}", "task:generate_search_query"]}
        )
        query = response.content.strip()
        logger.info(f"--- [Search Coordinator] 생성된 검색어: {query} ---")
        return query

    except Exception as e:
        logger.error(f"!!! 'Search Coordinator' 실행 중 오류 발생: {e}", exc_info=True)
        return None

# 개별 에이전트의 입장 변화를 분석하는 AI 호출 함수
async def _get_single_stance_change(
    agent_name: str, prev_statement: str, current_statement: str, discussion_id: str, turn_number: int
) -> dict:
    logger.info(f"--- [Stance Analysis] Agent: {agent_name}, Turn: {turn_number} 분석 시작 ---")
    try:
        analyst_setting = await AgentSettings.find_one(
            AgentSettings.name == "Stance Analyst", AgentSettings.status == "active"
        )
        # 1. Stance Analyst 에이전트를 DB에서 찾았는지 확인
        if not analyst_setting:
            # logger.warning("!!! [Stance Analysis] 'Stance Analyst' 에이전트를 DB에서 찾을 수 없거나 'active' 상태가 아닙니다.")
            return {"agent_name": agent_name, "change": "분석 불가", "icon": "❓"}
        # logger.info("'Stance Analyst' 에이전트 설정을 성공적으로 찾았습니다.")

        transcript_to_analyze = (
            f"에이전트 이름: {agent_name}\n\n"
            f"이전 발언: \"{prev_statement}\"\n\n"
            f"현재 발언: \"{current_statement}\""
        )
        # 2. AI에게 전달될 최종 프롬프트 내용을 로그로 출력
        # logger.info(f"--- AI에게 전달될 프롬프트 ---\n{transcript_to_analyze}\n---------------------------")

        analyst_agent = ChatGoogleGenerativeAI(model=analyst_setting.config.model)
        structured_llm = analyst_agent.with_structured_output(StanceAnalysis)
        prompt = ChatPromptTemplate.from_messages([
            ("system", analyst_setting.config.prompt),
            ("human", "다음 토론 대화록을 분석하세요:\n\n{transcript}")
        ])
        chain = prompt | structured_llm
        
        analysis = await chain.ainvoke(
            {"transcript": transcript_to_analyze},
            config={"tags": [f"discussion_id:{discussion_id}", f"turn:{turn_number}", "task:stance_analysis"]}
        )
        
        # 3. AI의 응답이 성공적으로 파싱되었는지 확인
        # logger.info(f"성공적으로 AI 응답을 파싱했습니다: {analysis}")
        
        icon_map = {"유지": "😐", "강화": "🔼", "수정": "🔄", "약화": "🔽"}
        return {"agent_name": agent_name, "change": analysis.change, "icon": icon_map.get(analysis.change, "❓")}
    
    except Exception as e:
        # 4. 오류 발생 시, 정확한 오류 메시지를 로그로 출력
        logger.error(f"!!! [Stance Analysis] 에러 발생: Agent '{agent_name}'의 입장 분석 중 실패. 에러: {e}", exc_info=True)
        return {"agent_name": agent_name, "change": "분석 불가", "icon": "❓"}

# 모든 참여자의 입장 변화를 병렬로 분석하는 메인 함수
async def _analyze_stance_changes(transcript: List[dict], jury_members: List[dict], discussion_id: str, turn_number: int) -> List[dict]:
    """
    [고도화 버전] 전체 토론 기록을 바탕으로 각 에이전트의 최신 발언 2개를 정확히 찾아
    입장 변화를 안정적으로 분석합니다.
    """
    logger.info(f"--- [Stance Analysis] Robust analysis started for Turn: {turn_number} ---")

    # 1. 토론이 최소 1라운드는 진행되어야 비교가 가능하므로 이 조건은 유효합니다.
    if turn_number < 1:
        logger.warning(f"Analysis conditions not met (Turn: {turn_number} < 1). Skipping analysis.")
        return []

    # 2. [핵심 로직] 전체 transcript를 순회하며 전문가 에이전트들의 발언만 따로 수집합니다.
    jury_names = {member['name'] for member in jury_members}
    statements_by_agent = {name: [] for name in jury_names}

    for turn in transcript:
        agent_name = turn.get('agent_name')
        if agent_name in jury_names:
            statements_by_agent[agent_name].append(turn['message'])

    # 3. 각 에이전트별로 2개 이상의 발언이 쌓였는지 확인하고 분석 작업을 생성합니다.
    tasks = []
    for agent_config in jury_members:
        agent_name = agent_config['name']
        agent_statements = statements_by_agent[agent_name]

        # 해당 에이전트의 발언이 2개 이상일 경우에만 분석 목록에 추가합니다.
        if len(agent_statements) >= 2:
            prev_statement = agent_statements[-2]   # 뒤에서 두 번째 발언
            current_statement = agent_statements[-1] # 가장 최신 발언

            task = _get_single_stance_change(
                agent_name,
                prev_statement,
                current_statement,
                discussion_id,
                turn_number
            )
            tasks.append(task)
        else:
            logger.info(f"--- [Stance Analysis] Agent '{agent_name}' has only {len(agent_statements)} statement(s), not enough for comparison yet.")

    if not tasks:
        logger.warning("No agents have enough statements for stance change analysis in this round.")
        return []

    # 4. 생성된 분석 작업들을 병렬로 실행하고 결과를 반환합니다.
    results = await asyncio.gather(*tasks)
    logger.info(f"--- [Stance Analysis] Analysis complete. Returning {len(results)} results. ---")

    return results

# 라운드 요약 분석을 위한 Pydantic 모델
class CriticalUtterance(BaseModel):
    agent_name: str
    message: str

async def _get_round_summary(transcript_str: str, discussion_id: str, turn_number: int) -> dict:
    """라운드 대화록을 분석하여 결정적 발언을 선정하는 AI 에이전트를 호출합니다."""
    try:
        # DB에서 Round Analyst 에이전트 설정을 가져옵니다.
        analyst_setting = await AgentSettings.find_one(
            AgentSettings.name == "Round Analyst", AgentSettings.status == "active"
        )
        if not analyst_setting: return None

        analyst_agent = ChatGoogleGenerativeAI(model=analyst_setting.config.model)
        structured_llm = analyst_agent.with_structured_output(CriticalUtterance)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", analyst_setting.config.prompt),
            ("human", "Analyze the following transcript:\n\n{transcript}")
        ])
        
        chain = prompt | structured_llm
        summary = await chain.ainvoke(
            {"transcript": transcript_str},
            config={"tags": [f"discussion_id:{discussion_id}", f"turn:{turn_number}", "task:summarize"]}
        )
        return summary.dict()
    except Exception as e:
        logger.error(f"Error getting round summary: {e}")
        return None

async def _run_single_agent_turn(
    agent_config: dict,
    topic: str,
    history: str,
    evidence: str,
    special_directive: str,
    discussion_id: str,
    turn_count: int
) -> str:
    """단일 에이전트의 발언(turn)을 생성합니다. 모든 에이전트는 필요 시 웹 검색 도구를 사용할 수 있습니다."""
    agent_name = agent_config.get("name", "Unknown Agent")
    logger.info(f"--- [Flow] Running turn for agent: {agent_name} (Discussion: {discussion_id}, Turn: {turn_count}) ---")

    try:
        #llm = ChatGoogleGenerativeAI(
        #    model=agent_config.get("model", "gemini-1.5-pro"),
        #    temperature=agent_config.get("temperature", 0.2)
        #)
        # 헬퍼 함수를 통해 모델 이름에 맞는 클라이언트를 동적으로 가져옴
        model_name = agent_config.get("model", "gemini-1.5-pro")
        temperature = agent_config.get("temperature", 0.2)
        llm = get_llm_client(model_name=model_name, temperature=temperature)

        human_instruction = (
            "지금은 '모두 변론' 시간입니다. 위 내용을 바탕으로 당신의 초기 입장을 최소 100자에서 최대 300자 이내로 설명해주세요."
            if turn_count == 0 else
            f"지금은 '{turn_count + 1}차 토론' 시간입니다. 이전의 에이전트들의 의견을 고려하여 다른 에이전트의 주장을 반박하거나 다른 에이전트의 의견에 적극 동조하거나 아니면 다른 에이전트의 의견을 수렴하여 의견을 수정한 당신의 의견을 주장합니다. 다른 에이전트의 논리적 모순이나 사실에 위배되는 주장이 있다고 생각한다면 적극적으로 반박하십시요. 다른 에이전트가 생각하지 못하는 새로운 아이디어, 독창적인 주장, 그리고 토론의 주제를 심화할 수 있다고 생각되는 내용을 적극적으로 주장합니다. 또한, 이전 토론 차수에서 주장한 내용을 바탕으로 자신의 주장중에 보다 구체적인 대안, 구체적인 방안등으로 자신의 주장을 심화 발전하는 것이 중요합니다. 토론의 차수가 높아질수록 이전 자신의 주장을 동어반복하기 보단 보다 구체적인 대안을 주장합니다. 주장은 최소 100자 최대 300자 이내로 추가해주세요."
        )

        final_human_prompt = (
            f"당신은 다음 토론에 참여하는 AI 에이전트입니다. 주어진 참고 자료와 토론 내용을 바탕으로 당신의 임무를 수행하세요.\n\n"
            f"### 전체 토론 주제: {topic}\n\n"
            f"### 참고 자료 (초기 분석 정보)\n{evidence}\n"
            f"### 지금까지의 토론 내용:\n{history if history else '아직 토론 내용이 없습니다.'}\n\n"
            f"{special_directive}\n"
            f"### 당신의 임무\n{human_instruction}"
        )

        logger.info(f"--- [Flow] Agent '{agent_name}' will now decide on tool usage autonomously. ---")
        
        original_system_prompt = agent_config.get("prompt", "You are a helpful assistant.")
        tool_system_prompt = SYSTEM_TOOL_INSTRUCTION_BLOCK + "\n\n" + original_system_prompt

        prompt = ChatPromptTemplate.from_messages([
            ("system", tool_system_prompt),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        tools = [web_search_tool]
        agent = create_tool_calling_agent(llm, tools, prompt)
        agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
        
        response = await agent_executor.ainvoke(
            {"input": final_human_prompt},
            config={"tags": [f"discussion_id:{discussion_id}", f"agent_name:{agent_name}", f"turn:{turn_count}"]}
        )
        output = response.get("output", "오류: 응답을 생성하지 못했습니다.")
        
        # 1. LangChain 응답이 AIMessage 같은 객체일 경우, .content 속성을 먼저 추출합니다.
        if isinstance(output, BaseMessage):
            content = output.content
        else:
            content = output

        # 2. content가 Anthropic 모델의 응답 형식인 list일 경우를 처리합니다.
        #    ex: [{'type': 'text', 'text': '...'}]
        if isinstance(content, list):
            # 리스트 안의 딕셔너리에서 'text' 키를 가진 값들을 모두 찾아 합칩니다.
            return "\n".join(
                block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
            )
        
        # 3. Gemini, OpenAI 등의 일반적인 문자열 응답을 처리합니다.
        return str(content)

    except Exception as e:
        logger.error(f"--- [Flow Error] Agent '{agent_name}' turn failed: {e} ---", exc_info=True)
        return f"({agent_name} 발언 생성 중 오류 발생)"
    
# 토론 흐름도 분석을 위한 헬퍼 함수
async def _analyze_flow_data(transcript: List[dict], jury_members: List[dict], discussion_id: str, turn_number: int) -> dict:
    """
    LLM 기반 'Interaction Analyst'를 사용하여 토론의 상호작용을 분석합니다.
    """
    logger.info(f"--- [Flow Analysis] LLM-based interaction analysis started for Turn: {turn_number} ---")
    
    # 1. 현재 라운드의 대화만 문자열로 추출
    current_round_transcript_str = "\n\n".join(
        [f"{turn['agent_name']}: {turn['message']}" for turn in transcript[-len(jury_members):]]
    )

    try:
        # 2. DB에서 Interaction Analyst 에이전트 설정을 가져옵니다.
        analyst_setting = await AgentSettings.find_one(
            AgentSettings.name == "Interaction Analyst", AgentSettings.status == "active"
        )
        if not analyst_setting:
            logger.error("!!! [Flow Analysis] 'Interaction Analyst' 에이전트를 DB에서 찾을 수 없습니다.")
            return {"interactions": []}

        # 3. LLM 및 체인 구성
        llm = ChatGoogleGenerativeAI(model=analyst_setting.config.model, temperature=analyst_setting.config.temperature)
        structured_llm = llm.with_structured_output(InteractionAnalysisResult)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", analyst_setting.config.prompt),
            ("human", "Please analyze the following transcript:\n\n{transcript}")
        ])
        chain = prompt | structured_llm

        # 4. LLM 호출하여 분석 실행
        analysis_result = await chain.ainvoke(
            {"transcript": current_round_transcript_str},
            config={"tags": [f"discussion_id:{discussion_id}", f"turn:{turn_number}", "task:flow_analysis"]}
        )

        # 5. Pydantic 모델을 프론트엔드가 사용하는 딕셔너리 리스트로 변환
        # Pydantic 모델의 alias('from', 'to', 'type')를 원래 필드명으로 변환
        interactions_list = [
            {
                "from": interaction.from_agent,
                "to": interaction.to_agent,
                "type": interaction.interaction_type
            }
            for interaction in analysis_result.interactions
        ]

        # --- 중복된 상호작용을 제거하는 로직 추가 ---
        # (from, to)를 키로 사용하는 딕셔너리를 사용하여 관계를 관리합니다.
        prioritized_interactions = {}

        for interaction in interactions_list:
            # (from, to) 쌍을 고유 키로 사용합니다.
            interaction_key = (interaction['from'], interaction['to'])
            
            # 1. 이 관계가 처음 발견된 경우, 사전에 추가합니다.
            if interaction_key not in prioritized_interactions:
                prioritized_interactions[interaction_key] = interaction
            else:
                # 2. 이미 관계가 존재할 경우, 우선순위 규칙을 적용합니다.
                existing_type = prioritized_interactions[interaction_key]['type']
                new_type = interaction['type']
                
                # 기존 관계가 'agreement'이고 새로운 관계가 'disagreement'일 때만 교체합니다.
                if existing_type == 'agreement' and new_type == 'disagreement':
                    prioritized_interactions[interaction_key] = interaction

        # 최종적으로 필터링된 상호작용 목록을 딕셔너리의 값들로 생성합니다.
        final_interactions = list(prioritized_interactions.values())
        
        logger.info(f"--- [Flow Analysis] Analysis complete. Found {len(interactions_list)} interactions, returning {len(final_interactions)} prioritized interactions. ---")
        return {"interactions": final_interactions} # 우선순위가 적용된 최종 리스트를 반환

    except Exception as e:
        logger.error(f"!!! [Flow Analysis] Error during interaction analysis: {e}", exc_info=True)
        return {"interactions": []}

# 투표 생성을 위한 별도의 헬퍼 함수
async def _generate_vote_options(transcript_str: str, discussion_id: str, turn_number: int, vote_history: List[str], topic: str) -> Optional[dict]:
    """
    대화록과 토론 주제를 분석하여 새로운 투표 주제와 선택지를 생성합니다.
    - TypeError 방지를 위해 topic 인자를 받습니다.
    - KeyError 방지를 위해 대화록의 중괄호를 이스케이프 처리합니다.
    - JSON 파싱 오류 방지를 위해 안정적인 2단계 파싱 로직을 사용합니다.
    - 한글 오타 방지를 위해 '핵심 용어' 가이드라인을 동적으로 생성합니다.
    """
    logger.info(f"--- [Vote Generation] Turn: {turn_number} 투표 생성 시작 ---")
    raw_response = ""
    json_str = ""
    try:
        vote_caster_setting = await AgentSettings.find_one(
            AgentSettings.name == "Vote Caster", AgentSettings.status == "active"
        )
        if not vote_caster_setting:
            logger.error("!!! [Vote Generation] 'Vote Caster' 에이전트를 DB에서 찾을 수 없습니다.")
            return None

        # 이전 투표 기록 섹션 생성
        history_prompt_section = "아직 사용자의 이전 투표 기록이 없습니다."
        if vote_history:
            history_items = "\n".join([f"- '{item}'" for item in vote_history])
            history_prompt_section = f"### 이전 투표에서 사용자가 선택한 항목들:\n{history_items}"

        # 2. 토론 주제를 바탕으로 '핵심 용어' 가이드라인을 동적으로 생성 (핵심 수정!)
        key_terms_guide = f"### Key Terms (Use these exact Korean spellings):\n- '{topic}'"

        # 대화록에 포함될 수 있는 중괄호를 이스케이프 처리하여 KeyError를 원천 방지
        safe_transcript_str = transcript_str.replace('{', '{{').replace('}', '}}')

        # 최종 프롬프트 조립
        final_human_prompt = (
            f"{key_terms_guide}\n\n" # <--- 한 줄 띄워서 가독성 확보
            f"{history_prompt_section}\n\n"
            f"### 현재 라운드까지의 전체 토론 대화록:\n{safe_transcript_str}"
        )

        # LLM 호출
        vote_caster_agent = ChatGoogleGenerativeAI(
            model=vote_caster_setting.config.model,
            temperature=vote_caster_setting.config.temperature,
            model_kwargs={"response_mime_type": "application/json"}
        )
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", vote_caster_setting.config.prompt),
            ("human", final_human_prompt)
        ])
        
        chain = prompt | vote_caster_agent
        response = await chain.ainvoke(
            {},
            config={"tags": [f"discussion_id:{discussion_id}", f"turn:{turn_number}", "task:generate_vote"]}
        )

        raw_response = response.content
        
        # 안정적인 2단계 파싱 로직
        # 1. LLM 응답에서 마크다운 코드 블록 제거
        match = re.search(r"```(json)?\s*({.*?})\s*```", raw_response, re.DOTALL)
        json_str = match.group(2) if match else raw_response

        # 2. Python 기본 json 라이브러리로 먼저 파싱
        parsed_json = json.loads(json_str)
        
        # 3. 파싱된 딕셔너리를 Pydantic으로 검증
        vote_content = VoteContent.model_validate(parsed_json)
        
        logger.info(f"--- [Vote Generation] 투표 생성 및 파싱 완료: {vote_content.topic} ---")
        return vote_content.model_dump()
        
    except (ValidationError, json.JSONDecodeError) as e:
        logger.error(f"!!! [Vote Generation] JSON 파싱/검증 오류. 오류: {e}\n원본 응답: {raw_response}", exc_info=True)
        # 파싱 실패 시, 사용자에게 다음 라운드로 넘어갈 수 있는 기본 옵션 제공
        return {
            "topic": "다음으로 어떤 토론을 진행할까요?",
            "options": ["가장 의견이 엇갈리는 쟁점에 대해 추가 반론", "새로운 관점의 전문가 추가 투입 요청", "현재까지 내용 중간 요약"]
        }
    except Exception as e:
        logger.error(f"!!! [Vote Generation] 투표 생성 중 알 수 없는 오류 발생: {e}", exc_info=True)
        return None
    
async def execute_turn(discussion_log: DiscussionLog, user_vote: Optional[str] = None, model_overrides: Optional[Dict[str, str]] = None):
    """
    백그라운드에서 단일 토론 턴을 실행하고, 결과를 DB에 기록합니다.
    사용자의 투표 기록은 Redis를 통해 세션으로 관리합니다.
    """
    logger.info(f"--- [BG Task] Executing turn for Discussion ID: {discussion_log.discussion_id} ---")

     # --- 사용자 선택 모델 적용 로직 ---
    if model_overrides:
        logger.info(f"--- [BG Task] Applying model overrides: {model_overrides} ---")
        # discussion_log에 저장된 참여자 목록을 순회
        for participant in discussion_log.participants:
            agent_name = participant.get('name')
            # 사용자가 선택한 모델이 있는지 확인
            if agent_name in model_overrides:
                new_model = model_overrides[agent_name]
                original_model = participant.get('model')
                # 해당 에이전트의 모델을 사용자가 선택한 모델로 교체
                participant['model'] = new_model
                logger.info(f"--- [BG Task] Model for '{agent_name}' overridden: from '{original_model}' to '{new_model}' ---")

    # --- 사회자 안내 메시지 추가 ---
    # 사용자 투표가 있고, 첫 턴(모두 변론)이 아닐 때 사회자 안내 메시지를 먼저 추가합니다.
    if user_vote and discussion_log.turn_number > 0:
        round_name = "모두 변론" if discussion_log.turn_number == 1 else f"{discussion_log.turn_number - 1}차 토론"
        
        # '을(를)' 조사 처리
        last_char = user_vote[-1]
        postposition = "을" if (ord(last_char) - 0xAC00) % 28 > 0 else "를"

        moderator_message = (
            f"{round_name}이 종료되었습니다. "
            f"사용자는 '{discussion_log.current_vote['topic']}' 투표에 "
            f"'{user_vote}'{postposition} 선택하였습니다. 다음 토론을 시작합니다."
        )
        moderator_turn_data = {
            "agent_name": "사회자", 
            "message": moderator_message, 
            "timestamp": datetime.utcnow()
        }
        discussion_log.transcript.append(moderator_turn_data)
    
    redis_key = f"vote_history:{discussion_log.discussion_id}"
    vote_history = []
    try:
        history_json = await db.redis_client.get(redis_key)
        if history_json:
            vote_history = json.loads(history_json)
    except Exception as e:
        logger.error(f"!!! [Redis Error] Redis에서 투표 기록을 가져오는 중 오류 발생: {e}", exc_info=True)

    if user_vote:
        vote_history.append(user_vote)
        try:
            await db.redis_client.set(redis_key, json.dumps(vote_history), ex=86400)
            logger.info(f"--- [BG Task] 사용자 투표 '{user_vote}'를 Redis에 기록했습니다. 현재 기록: {vote_history} ---")
        except Exception as e:
            logger.error(f"!!! [Redis Error] Redis에 투표 기록을 저장하는 중 오류 발생: {e}", exc_info=True)

    # --- 중앙 검색 로직 시작 ---
    central_search_results_str = ""
    # 첫 턴(모두 변론)이 아니면서 사용자 투표가 있을 때만 검색 수행
    if discussion_log.turn_number > 0 and user_vote:
        search_query = await _get_search_query(discussion_log, user_vote)
        if search_query:
            # search.py의 비동기 함수 사용
            search_results = await perform_web_search_async(search_query)
            if search_results:
                formatted_results = "\n".join([
                    f"- 출처: {res['url']}\n- 요약: {res['content']}" 
                    for res in search_results
                ])
                central_search_results_str = f"--- [중앙 집중식 웹 검색 결과]\n{formatted_results}\n---"

    current_turn = discussion_log.turn_number
    history_str = "\n\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript])

    # DB에 저장된 증거 자료를 불러와 프롬프트에 포함할 문자열로 만듭니다.
    evidence_str = ""
    if discussion_log.evidence_briefing:
        web_evidence = "\n".join([f"- {item['summary']} (출처: {item['source']})" for item in discussion_log.evidence_briefing.get('web_evidence', [])])
        file_evidence = "\n".join([f"- {item['summary']} (출처: {item['source']})" for item in discussion_log.evidence_briefing.get('file_evidence', [])])
        
        evidence_str += "--- [참고 자료: 웹 검색 결과 요약] ---\n"
        evidence_str += web_evidence + "\n" if web_evidence else "관련 웹 검색 결과가 없습니다.\n"
        evidence_str += "--- [참고 자료: 제출 파일 요약] ---\n"
        evidence_str += file_evidence + "\n" if file_evidence else "제출된 파일이 없습니다.\n"

    # 중앙 검색 결과를 기존 evidence_str에 추가합니다.
    if central_search_results_str:
        evidence_str += "\n\n" + central_search_results_str

    special_directive = ""
    if user_vote:
        special_directive = (
            f"\n\n--- 특별 지시문 ---\n"
            f"사용자는 직전 라운드에서 '{user_vote}' 관점에 대한 당신의 의견을 듣고싶어합니다."
            f"이 관점을 포함하여 당신의 주장을 강화 또는 수정하거나 다른 에이전트들의 주장을 반박하십시오."
            f"그러나 이 관점이 당신의 생각에 중요하지 않다면 이 토론이 어떤 방향에 중점을 두어야 하는지 앞으로 어떤 논의를 심화 발전시켜야 하는지 오히려 적극적으로 당신의 주장을 펼칠수도 있습니다."
            f"\n-------------------\n"
        )

    excluded_roles = ["재판관", "사회자"]
    jury_members = [p for p in discussion_log.participants if p.get('name') not in excluded_roles]

    # --- 에이전트 발언을 순차 실행에서 동시 실행으로 변경 ---

    # 1. 모든 에이전트의 비동기 작업을 담을 리스트를 생성합니다.
    tasks = []
    for agent_config in jury_members:
        # 2. await로 즉시 실행하는 대신, 실행할 작업(코루틴)을 만들어 tasks 리스트에 추가합니다.
        task = _run_single_agent_turn(
            agent_config, 
            discussion_log.topic, 
            history_str, 
            evidence_str,  # 증거 자료 전달
            special_directive,
            discussion_log.discussion_id,
            current_turn
        )
        tasks.append(task)

    # 3. asyncio.gather를 사용해 모든 작업을 동시에 실행하고, 모든 결과가 도착할 때까지 기다립니다.
    logger.info(f"--- [BG Task] {len(tasks)}명의 에이전트 발언을 동시에 생성 시작... (ID: {discussion_log.discussion_id})")
    messages = await asyncio.gather(*tasks)
    logger.info(f"--- [BG Task] 모든 에이전트 발언 생성 완료. (ID: {discussion_log.discussion_id})")

    # 4. 이제 모든 답변이 도착했으므로, 결과를 순서대로 transcript에 추가합니다.
    for i, message in enumerate(messages):
        agent_name = jury_members[i]['name']
        
        # 1. 전문가의 메인 발언을 추가합니다.
        main_turn_data = {"agent_name": agent_name, "message": message, "timestamp": datetime.utcnow()}
        discussion_log.transcript.append(main_turn_data)

        # 2. 메인 발언에 대해 Staff 에이전트들을 동기적으로 실행합니다.
        # (asyncio.to_thread를 사용해 non-blocking 방식으로 호출)
        snr_result = await asyncio.to_thread(run_snr_agent, message)
        if snr_result:
            snr_turn_data = {
                "agent_name": "SNR 전문가", 
                "message": json.dumps(snr_result, ensure_ascii=False), # 결과를 JSON 문자열로 저장
                "timestamp": datetime.utcnow()
            }
            discussion_log.transcript.append(snr_turn_data)

        verifier_result = await asyncio.to_thread(run_verifier_agent, message)
        if verifier_result:
            verifier_turn_data = {
                "agent_name": "정보 검증부", 
                "message": json.dumps(verifier_result, ensure_ascii=False), # 결과를 JSON 문자열로 저장
                "timestamp": datetime.utcnow()
            }
            discussion_log.transcript.append(verifier_turn_data)

    # --- 라운드 종료 구분선 추가] ---
    round_name_for_separator = "모두 변론" if discussion_log.turn_number == 0 else f"{discussion_log.turn_number}차 토론"
    separator_message = f"---------- {round_name_for_separator} 종료 ----------"
    separator_turn_data = {
        "agent_name": "구분선", 
        "message": separator_message, 
        "timestamp": datetime.utcnow()
    }
    discussion_log.transcript.append(separator_turn_data)
    
    logger.info(f"--- [BG Task] 라운드 {current_turn} 완료. 분석을 시작합니다... (ID: {discussion_log.discussion_id})")
    
    # 분석에 필요한 최신 대화록 문자열 생성 (이번 라운드 발언만)
    final_transcript_str = "\n\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript[-len(jury_members):]])
    
    analysis_tasks = {
        "round_summary": _get_round_summary(final_transcript_str, discussion_log.discussion_id, discussion_log.turn_number),
        "stance_changes": _analyze_stance_changes(discussion_log.transcript, jury_members, discussion_log.discussion_id, discussion_log.turn_number),
        "flow_data": _analyze_flow_data(discussion_log.transcript, jury_members, discussion_log.discussion_id, discussion_log.turn_number)
    }
    
    analysis_results = await asyncio.gather(*analysis_tasks.values())
    analysis_map = dict(zip(analysis_tasks.keys(), analysis_results))

    discussion_log.round_summary = {
        "critical_utterance": analysis_map.get("round_summary"),
        "stance_changes": analysis_map.get("stance_changes")
    }
    discussion_log.flow_data = analysis_map.get("flow_data")

    logger.info(f"--- [BG Task] 분석 완료. 결과를 DB에 저장합니다. (ID: {discussion_log.discussion_id})")
    
    # 다음 라운드를 위한 투표 생성
    full_history_str = "\n\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript])
    discussion_log.current_vote = await _generate_vote_options(
        full_history_str, 
        discussion_log.discussion_id, 
        discussion_log.turn_number,
        vote_history,
        discussion_log.topic
    )
    
    discussion_log.status = "waiting_for_vote"
    discussion_log.turn_number += 1
    
    await discussion_log.save()
    
    logger.info(f"--- [BG Task] Turn completed for {discussion_log.discussion_id}. New status: '{discussion_log.status}' ---")

# 모델 이름에 따라 적절한 LLM 클라이언트를 반환하는 헬퍼 함수 추가
def get_llm_client(model_name: str, temperature: float):
    """모델 이름을 기반으로 올바른 LangChain LLM 클라이언트 인스턴스를 생성합니다."""
    if model_name.startswith("gemini"):
        return ChatVertexAI(
            model_name=model_name, 
            temperature=temperature,
            location="asia-northeast3"
        )
    elif model_name.startswith("gpt"):
        return ChatOpenAI(model=model_name, temperature=temperature)
    elif model_name.startswith("claude"):
        return ChatAnthropic(model=model_name, temperature=temperature)
    else:
        # 알 수 없는 모델 이름일 경우, 기본 모델로 대체하여 오류 방지
        logger.warning(f"Unrecognized model name '{model_name}'. Falling back to Gemini 1.5 pro.")
        return ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=temperature)