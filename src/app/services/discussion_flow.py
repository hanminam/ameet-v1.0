# src/app/services/discussion_flow.py
# 미래에 구현될 복잡한 토론 로직을 임시로 대체하는 '기능적인 목업(Functional Mock)' 

import asyncio
from typing import List, Literal, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime

from pydantic import BaseModel

from app.schemas.orchestration import DebateTeam
from app.models.discussion import AgentSettings, DiscussionLog
from app.core.config import logger

from app.schemas.orchestration import AgentDetail # AgentDetail 스키마 추가

# 입장 변화 분석 결과 Pydantic 모델
class StanceAnalysis(BaseModel):
    change: Literal['유지', '강화', '수정', '약화']
    reason: str

# 개별 에이전트의 입장 변화를 분석하는 AI 호출 함수
async def _get_single_stance_change(
    agent_name: str, prev_statement: str, current_statement: str, discussion_id: str, turn_number: int
) -> dict:
    try:
        analyst_setting = await AgentSettings.find_one(
            AgentSettings.name == "Stance Analyst", AgentSettings.status == "active"
        )
        if not analyst_setting: return {"agent_name": agent_name, "change": "분석 불가", "icon": "❓"}

        analyst_agent = ChatGoogleGenerativeAI(model=analyst_setting.config.model)
        structured_llm = analyst_agent.with_structured_output(StanceAnalysis)
        prompt = ChatPromptTemplate.from_messages([
            ("system", analyst_setting.config.prompt),
            ("human", "다음 토론 대화록을 분석하세요:\n\n{transcript}")
        ])
        chain = prompt | structured_llm
        analysis = await chain.ainvoke(
            {}, config={"tags": [f"discussion_id:{discussion_id}", f"turn:{turn_number}", "task:stance_analysis"]}
        )
        
        icon_map = {"유지": "😐", "강화": "🔼", "수정": "🔄", "약화": "🔽"}
        return {"agent_name": agent_name, "change": analysis.change, "icon": icon_map.get(analysis.change, "❓")}
    except Exception:
        return {"agent_name": agent_name, "change": "분석 불가", "icon": "❓"}

# 모든 참여자의 입장 변화를 병렬로 분석하는 메인 함수
async def _analyze_stance_changes(transcript: List[dict], jury_members: List[dict], discussion_id: str, turn_number: int) -> List[dict]:
    num_jury = len(jury_members)
    # 비교할 이전 라운드가 없으면 빈 리스트 반환
    if turn_number < 1 or len(transcript) < num_jury * 2:
        return []

    # 현재 라운드와 이전 라운드의 발언을 에이전트 이름으로 매핑
    current_round_map = {turn['agent_name']: turn['message'] for turn in transcript[-num_jury:]}
    prev_round_map = {turn['agent_name']: turn['message'] for turn in transcript[-num_jury*2:-num_jury]}

    tasks = []
    for agent in jury_members:
        agent_name = agent['name']
        # 두 라운드 모두에 발언이 있는 에이전트만 분석 대상으로 추가
        if agent_name in prev_round_map and agent_name in current_round_map:
            task = _get_single_stance_change(
                agent_name, 
                prev_round_map[agent_name], 
                current_round_map[agent_name], 
                discussion_id, 
                turn_number
            )
            tasks.append(task)
    
    if not tasks:
        return []
    return await asyncio.gather(*tasks)

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
    special_directive: str, 
    discussion_id: str,
    turn_count: int
) -> str:
    """단일 에이전트의 발언(turn)을 생성합니다."""
    agent_name = agent_config.get("name", "Unknown Agent")
    logger.info(f"--- [Flow] Running turn for agent: {agent_name} (Discussion: {discussion_id}, Turn: {turn_count}) ---")
    
    try:
        llm = ChatGoogleGenerativeAI(
            model=agent_config.get("model", "gemini-1.5-flash"),
            temperature=agent_config.get("temperature", 0.2)
        )
        
        # [수정] 토론 라운드 수에 따라 동적으로 지시사항을 변경
        if turn_count == 0:  # 첫 번째 라운드 (모두 변론)
            human_instruction = "지금은 '모두 변론' 시간입니다. 위 내용을 바탕으로 당신의 초기 입장을 최소 200자에서 최대 1000자 이내로 설명해주세요."
        else:  # 두 번째 라운드 이후 (반론)
            human_instruction = f"지금은 '{turn_count + 1}차 토론' 시간입니다. 이전의 에이전트들의 의견을 고려하여 다른 에이전트의 주장을 반박하거나 다른 에이전트의 의견에 적극 동조하거나 아니면 다른 에이전트의 의견을 수렴하여 의견을 수정한 당신의 의견을 최소 100자 최대 500자 이내로 추가해주세요."

        # 최종 프롬프트 구성
        final_human_prompt = (
            f"주제: {topic}\n\n"
            f"지금까지의 토론 내용:\n{history}\n\n"
            f"{special_directive}\n"
            f"{human_instruction}"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", agent_config.get("prompt", "You are a helpful assistant.")),
            ("human", final_human_prompt)
        ])
        
        chain = prompt | llm
        
        response = await chain.ainvoke(
            {"topic": topic, "history": history, "special_directive": special_directive},
            config={"tags": [f"discussion_id:{discussion_id}", f"agent_name:{agent_name}", f"turn:{turn_count}"]}
        )
        
        return response.content
        
    except Exception as e:
        logger.error(f"--- [Flow Error] Agent '{agent_name}' turn failed: {e} ---")
        return f"({agent_name} 발언 생성 중 오류 발생)"
    
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
    
async def execute_turn(discussion_log: DiscussionLog, user_vote: Optional[str] = None):
    """
    백그라운드에서 단일 토론 턴을 실행하고, 결과를 DB에 기록합니다.
    """
    logger.info(f"--- [BG Task] Executing turn for Discussion ID: {discussion_log.discussion_id} ---")
    
    current_turn = discussion_log.turn_number  # [수정] DB에서 현재 턴 번호를 가져옴

    # 1. 컨텍스트 준비
    current_transcript = [f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript]
    history_str = "\n\n".join(current_transcript)

    # 2. '특별 지시문' 생성
    special_directive = ""
    if user_vote:
        special_directive = (
            f"\n\n--- 특별 지시문 ---\n"
            f"사용자는 직전 라운드에서 '{user_vote}' 관점을 더 중요하게 선택했습니다. "
            f"이 관점을 중심으로 당신의 주장을 강화하거나 상대방의 주장을 반박하십시오."
            f"\n-------------------\n"
        )
    
    # 3. 에이전트 순차 실행
    excluded_roles = ["재판관", "사회자"]
    jury_members = [p for p in discussion_log.participants if p.get('name') not in excluded_roles]

    for agent_config in jury_members:
        message = await _run_single_agent_turn(
            agent_config, 
            discussion_log.topic, 
            history_str, 
            special_directive,
            discussion_log.discussion_id,
            current_turn  # 현재 턴 번호를 인자로 전달
        )
        
        # 4. 실시간 DB 업데이트
        turn_data = {
            "agent_name": agent_config['name'], 
            "message": message, 
            "timestamp": datetime.utcnow()
        }
        discussion_log.transcript.append(turn_data)
        await discussion_log.save()
        
        history_str += f"\n\n{agent_config['name']}: {message}"
        await asyncio.sleep(1)

    # 라운드 종료 후 UX 데이터 생성 (MVP 단계에서는 목업 데이터 사용)
    if jury_members and discussion_log.transcript:
        transcript_for_summary = "\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript])
        
        # 1. 결정적 발언 선정 (AI 호출 + Fallback)
        critical_utterance_data = await _get_round_summary(transcript_for_summary, discussion_log.discussion_id, discussion_log.turn_number)
        if not critical_utterance_data: # AI 호출 실패 시
            current_round_transcript = discussion_log.transcript[-len(jury_members):]
            # 가장 긴 발언을 결정적 발언으로 선정
            longest_turn = max(current_round_transcript, key=lambda x: len(x['message']))
            critical_utterance_data = {
                "agent_name": longest_turn['agent_name'],
                "message": (longest_turn['message'][:80] + "...") if len(longest_turn['message']) > 80 else longest_turn['message']
            }

        # 2. 입장 변화 데이터 생성 (AI 기반 분석)
        stance_changes_data = await _analyze_stance_changes(
            discussion_log.transcript, jury_members, discussion_log.discussion_id, discussion_log.turn_number
        )
        discussion_log.round_summary = {
            "critical_utterance": critical_utterance_data,
            "stance_changes": stance_changes_data
        }

        # 3. 토론 흐름도 데이터 생성 (대화 내용 기반)
        discussion_log.flow_data = _analyze_flow_data(discussion_log.transcript, jury_members)

    # 5. 최종 상태 변경
    discussion_log.status = "waiting_for_vote"
    discussion_log.turn_number += 1
    await discussion_log.save()
    
    logger.info(f"--- [BG Task] Turn completed for {discussion_log.discussion_id}. New status: '{discussion_log.status}' ---")


async def run_discussion_flow(discussion_id: str, debate_team: DebateTeam, topic: str):
    """
    백그라운드에서 전체 토론 흐름을 실행하고, 각 발언을 DB에 기록합니다.
    """
    logger.info(f"--- [Flow BG Task] Started for Discussion ID: {discussion_id} ---")
    
    discussion_log = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    if not discussion_log:
        logger.error(f"--- [Flow BG Task Error] DiscussionLog not found for ID: {discussion_id} ---")
        return

    current_transcript = []
    
    # 1. 모두 변론 (Opening Statements)
    logger.info(f"--- [Flow] Starting Opening Statements for {discussion_id} ---")
    history_str = "토론이 시작되었습니다. 각자 의견을 말씀해주세요."
    
    # 에이전트들을 순차적으로 실행 (병렬 실행도 가능하나, 순차 진행이 토론 흐름에 더 적합)
    for agent_detail in debate_team.jury:
        # DB에서 최신 active 설정을 다시 가져오는 것이 더 정확하지만, MVP에서는 전달받은 config 사용
        agent_config = {
            "prompt": agent_detail.prompt,
            "model": agent_detail.model,
            "temperature": agent_detail.temperature
        }

        message = await _run_single_agent_turn(
            agent_detail.name, agent_config, topic, history_str, discussion_id
        )
        
        # DB에 발언 기록
        turn_data = {"agent_name": agent_detail.name, "message": message, "timestamp": datetime.utcnow()}
        discussion_log.transcript.append(turn_data)
        await discussion_log.save()
        
        # 다음 에이전트를 위해 대화 기록 업데이트
        current_transcript.append(f"{agent_detail.name}: {message}")
        history_str = "\n\n".join(current_transcript)
        
        await asyncio.sleep(1) # 실제 토론처럼 보이게 약간의 딜레이

    # 2. 최종 결론 및 상태 업데이트 (MVP에서는 간단히 처리)
    # TODO: 향후 'n차 토론', '최종 변론' 등 복잡한 로직 추가
    
    discussion_log.status = "completed"
    discussion_log.completed_at = datetime.utcnow()
    discussion_log.report_summary = "토론이 성공적으로 완료되었습니다." # 실제 요약 로직 추가 필요
    await discussion_log.save()

    logger.info(f"--- [Flow BG Task] Completed for Discussion ID: {discussion_id} ---")