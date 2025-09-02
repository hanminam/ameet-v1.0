# src/app/services/discussion_flow.py
# 미래에 구현될 복잡한 토론 로직을 임시로 대체하는 '기능적인 목업(Functional Mock)' 

import asyncio
import json
from typing import List, Literal, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from app.tools.search import web_search_tool
from datetime import datetime

from pydantic import BaseModel, ValidationError

from app import db
from app.db import redis_client

from app.schemas.orchestration import DebateTeam
from app.models.discussion import AgentSettings, DiscussionLog
from app.core.config import logger

from app.schemas.orchestration import AgentDetail # AgentDetail 스키마 추가
from app.schemas.discussion import VoteContent
import re

# 에이전트 및 도구 실행을 위한 LangChain 모듈 임포트
from langchain.agents import AgentExecutor, create_tool_calling_agent
from app.tools.search import available_tools

# ReAct 패턴을 적용한 강력한 시스템 레벨 도구 사용 규칙 정의
SYSTEM_TOOL_INSTRUCTION_BLOCK = """
---
### Tools Guide (VERY IMPORTANT)

You have access to the following tools. You must adhere to the following strict process for using them:

1.  **THOUGHT:** First, analyze the user's request, the debate topic, and the conversation history. Critically assess whether your internal knowledge is sufficient and up-to-date. If the topic involves recent events, specific data, or potentially controversial facts, you MUST consider using a tool.
2.  **ACTION:** If you decide to use a tool, you must format your response as a JSON object for the tool call. For example:
    ```json
    {
      "tool": "web_search",
      "tool_input": "Query to search on the web"
    }
    ```

3.  **FINAL ANSWER:** After you have gathered the necessary information from the tool (or decided that no tool is needed), formulate your comprehensive final answer based on all the information available to you.
**CRITICAL RULE:** Do NOT write about your intention to search in your final answer. Do NOT output text like `web_search(...)` or "I will search for...". You must either use the tool correctly by outputting the JSON action or provide a final answer without mentioning the tool.
---
"""

# 입장 변화 분석 결과 Pydantic 모델
class StanceAnalysis(BaseModel):
    change: Literal['유지', '강화', '수정', '약화']
    reason: str

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
    num_jury = len(jury_members)
    # logger.info(f"--- [Stance Analysis] 입장 변화 분석 시작. Turn: {turn_number}, Transcript Lenth: {len(transcript)}, Jury Members: {num_jury} ---")
    
    # 1. 분석을 실행할 조건이 맞는지 확인
    if turn_number < 1 or len(transcript) < num_jury * 2:
        # logger.warning(f"분석 조건 미충족으로 입장 변화 분석을 건너뜁니다. (Turn: {turn_number}, Transcript Lenth: {len(transcript)})")
        return []

    current_round_map = {turn['agent_name']: turn['message'] for turn in transcript[-num_jury:]}
    prev_round_map = {turn['agent_name']: turn['message'] for turn in transcript[-num_jury*2:-num_jury]}

    # 2. 이전 라운드와 현재 라운드의 발언이 올바르게 추출되었는지 확인
    # logger.info(f"이전 라운드 발언자: {list(prev_round_map.keys())}")
    # logger.info(f"현재 라운드 발언자: {list(current_round_map.keys())}")

    tasks = []
    for agent in jury_members:
        agent_name = agent['name']
        if agent_name in prev_round_map and agent_name in current_round_map:
            task = _get_single_stance_change(
                agent_name, 
                prev_round_map[agent_name], 
                current_round_map[agent_name], 
                discussion_id, 
                turn_number
            )
            tasks.append(task)
        else:
            # 3. 특정 에이전트의 발언이 누락되었는지 확인
            logger.warning(f"!!! '{agent_name}' 에이전트의 이전 또는 현재 발언이 없어 분석에서 제외됩니다.")
    
    if not tasks:
        # logger.warning("분석할 에이전트가 없습니다.")
        return []
        
    results = await asyncio.gather(*tasks)
    # logger.info(f"--- [Stance Analysis] 입장 변화 분석 완료. 결과 수: {len(results)} ---")
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
    """단일 에이전트의 발언(turn)을 생성합니다. 에이전트 설정에 따라 웹 검색 도구를 사용할 수 있습니다."""
    agent_name = agent_config.get("name", "Unknown Agent")
    logger.info(f"--- [Flow] Running turn for agent: {agent_name} (Discussion: {discussion_id}, Turn: {turn_count}) ---")

    try:
        llm = ChatGoogleGenerativeAI(
            model=agent_config.get("model", "gemini-1.5-flash"),
            temperature=agent_config.get("temperature", 0.2)
        )

        # 토론 라운드 수에 따라 동적으로 지시사항을 변경
        human_instruction = (
            "지금은 '모두 변론' 시간입니다. 위 내용을 바탕으로 당신의 초기 입장을 최소 100자에서 최대 500자 이내로 설명해주세요."
            if turn_count == 0 else
            f"지금은 '{turn_count + 1}차 토론' 시간입니다. 이전의 에이전트들의 의견을 고려하여 다른 에이전트의 주장을 반박하거나 다른 에이전트의 의견에 적극 동조하거나 아니면 다른 에이전트의 의견을 수렴하여 의견을 수정한 당신의 의견을 주장합니다. 다른 에이전트의 논리적 모순이나 사실에 위배되는 주장이 있다고 생각한다면 적극적으로 반박하십시요. 또한, 다른 에이전트가 생각하지 못하는 새로운 아이디어, 독창적인 주장, 그리고 토론의 주제를 심화할 수 있다고 생각되는 내용을 적극적으로 주장합니다. 또한, 이전 토론 차수에서 주장한 내용을 바탕으로 자신의 주장중에 보다 구체적인 대안, 구체적인 방안등으로 자신의 주장을 심화 발전하는 것이 중요합니다. 토론의 차수가 높아질수록 이전 자신의 주장을 동어반복하기 보단 보다 구체적인 대안을 주장합니다. 주장은 최소 200자 최대 500자 이내로 추가해주세요."
        )

        # 최종 프롬프트 구성 (기존의 불필요한 시스템 지시사항 제거)
        final_human_prompt = (
            f"당신은 다음 토론에 참여하는 AI 에이전트입니다. 주어진 참고 자료와 토론 내용을 바탕으로 당신의 임무를 수행하세요.\n\n"
            f"### 전체 토론 주제: {topic}\n\n"
            f"### 참고 자료 (초기 분석 정보)\n{evidence}\n"
            f"### 지금까지의 토론 내용:\n{history if history else '아직 토론 내용이 없습니다.'}\n\n"
            f"{special_directive}\n"
            f"### 당신의 임무\n{human_instruction}"
        )

        logger.info(f"--- [Flow] Agent '{agent_name}' will now decide on tool usage autonomously. ---")
        
        # ReAct 기반 도구 사용 규칙을 에이전트의 원래 시스템 프롬프트 앞에 추가
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
        return response.get("output", "오류: 응답을 생성하지 못했습니다.")
    
# 토론 흐름도 분석을 위한 헬퍼 함수
def _analyze_flow_data(transcript: List[dict], jury_members: List[dict]) -> dict:
    interactions = []
    agent_names = [agent['name'] for agent in jury_members]
    
    # 현재 라운드의 대화만 분석 (transcript는 전체 대화록)
    # 간단하게 마지막 jury_members 수만큼의 대화만 분석
    current_round_transcript = transcript[-len(jury_members):]

    for turn in current_round_transcript:
        speaker = turn['agent_name']
        message = turn['message']
        
        # 다른 에이전트의 이름이 언급되었는지 확인
        for mentioned_agent in agent_names:
            if speaker != mentioned_agent and mentioned_agent in message:
                interactions.append({"from": speaker, "to": mentioned_agent})
                
    return {"interactions": interactions}

# 투표 생성을 위한 별도의 헬퍼 함수
async def _generate_vote_options(transcript_str: str, discussion_id: str, turn_number: int, vote_history: List[str]) -> Optional[dict]:
    """대화록과 이전 투표 기록을 분석하여 새로운 투표 주제와 선택지를 생성합니다."""
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

        # [수정] 이전 투표 기록을 프롬프트에 명확하게 포함
        history_prompt_section = "아직 사용자의 이전 투표 기록이 없습니다."
        if vote_history:
            history_items = "\n".join([f"- '{item}'" for item in vote_history])
            history_prompt_section = f"### 이전 투표에서 사용자가 선택한 항목들 (이 항목들과 유사한 제안은 피하고, 더 심화된 새로운 관점을 제시하세요):\n{history_items}"

        # [수정] 프롬프트를 더 명확하고 구조적으로 변경
        final_human_prompt = (
            f"{history_prompt_section}\n\n"
            f"### 현재 라운드까지의 전체 토론 대화록:\n{transcript_str}"
        )

        vote_caster_agent = ChatGoogleGenerativeAI(
            model=vote_caster_setting.config.model,
            temperature=vote_caster_setting.config.temperature,
            # [추가] JSON 응답을 더 안정적으로 받기 위한 설정
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
        
        # LLM이 때때로 markdown 코드 블록을 포함하는 경우를 대비한 안정적인 파싱 로직
        match = re.search(r"```(json)?\s*({.*?})\s*```", raw_response, re.DOTALL)
        json_str = match.group(2) if match else raw_response
        
        # Pydantic 모델을 사용하여 유효성 검증
        vote_content = VoteContent.model_validate_json(json_str)
        
        logger.info(f"--- [Vote Generation] 투표 생성 및 파싱 완료: {vote_content.topic} ---")
        return vote_content.model_dump()
        
    except (ValidationError, json.JSONDecodeError) as e:
        logger.error(f"!!! [Vote Generation] JSON 파싱 오류. 오류: {e}\n원본 응답: {raw_response}", exc_info=True)
        # 파싱 실패 시, 사용자에게 다음 라운드로 넘어갈 수 있는 기본 옵션 제공
        return {
            "topic": "다음으로 어떤 토론을 진행할까요?",
            "options": ["가장 의견이 엇갈리는 쟁점에 대해 추가 반론", "새로운 관점의 전문가 추가 투입 요청", "현재까지 내용 중간 요약"]
        }
    except Exception as e:
        logger.error(f"!!! [Vote Generation] 투표 생성 중 알 수 없는 오류 발생: {e}", exc_info=True)
        return None
    
async def execute_turn(discussion_log: DiscussionLog, user_vote: Optional[str] = None):
    """
    백그라운드에서 단일 토론 턴을 실행하고, 결과를 DB에 기록합니다.
    사용자의 투표 기록은 Redis를 통해 세션으로 관리합니다.
    """
    logger.info(f"--- [BG Task] Executing turn for Discussion ID: {discussion_log.discussion_id} ---")
    
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

    # --- [핵심 수정] 에이전트 발언을 순차 실행에서 동시 실행으로 변경 ---

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
        turn_data = {"agent_name": agent_name, "message": message, "timestamp": datetime.utcnow()}
        discussion_log.transcript.append(turn_data)

    # --- [수정 완료] ---
        
    logger.info(f"--- [BG Task] 라운드 {current_turn} 완료. 분석을 시작합니다... (ID: {discussion_log.discussion_id})")
    
    # 분석에 필요한 최신 대화록 문자열 생성 (이번 라운드 발언만)
    final_transcript_str = "\n\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript[-len(jury_members):]])
    
    analysis_tasks = {
        "round_summary": _get_round_summary(final_transcript_str, discussion_log.discussion_id, discussion_log.turn_number),
        "stance_changes": _analyze_stance_changes(discussion_log.transcript, jury_members, discussion_log.discussion_id, discussion_log.turn_number),
        "flow_data": asyncio.to_thread(_analyze_flow_data, discussion_log.transcript, jury_members)
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
        vote_history
    )
    
    discussion_log.status = "waiting_for_vote"
    discussion_log.turn_number += 1
    
    await discussion_log.save()
    
    logger.info(f"--- [BG Task] Turn completed for {discussion_log.discussion_id}. New status: '{discussion_log.status}' ---")