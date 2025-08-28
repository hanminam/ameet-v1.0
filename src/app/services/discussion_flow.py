# src/app/services/discussion_flow.py
# 미래에 구현될 복잡한 토론 로직을 임시로 대체하는 '기능적인 목업(Functional Mock)' 

import asyncio
from typing import Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime

from pydantic import BaseModel

from app.schemas.orchestration import DebateTeam
from app.models.discussion import AgentSettings, DiscussionLog
from app.core.config import logger

from app.schemas.orchestration import AgentDetail # AgentDetail 스키마 추가

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
        # 1. 결정적 발언 선정 (AI 호출)
        transcript_for_summary = "\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript])
        critical_utterance_data = await _get_round_summary(transcript_for_summary, discussion_log.discussion_id, discussion_log.turn_number)
        
        # 2. 입장 변화 및 토론 흐름도 데이터 생성 (현재는 목업 유지)
        if discussion_log.turn_number > 0: # 첫 라운드(turn_number=0)에서는 입장 변화를 표시하지 않음
            discussion_log.round_summary = {
                "critical_utterance": critical_utterance_data,
                "stance_changes": [
                    {"agent_name": jury_members[0]['name'], "change": "유지", "icon": "😐"},
                    {"agent_name": jury_members[1]['name'], "change": "수정", "icon": "🔄"},
                ]
            }
        else: # 첫 라운드에서는 결정적 발언만 표시
            discussion_log.round_summary = {"critical_utterance": critical_utterance_data}

        discussion_log.flow_data = { "interactions": [{"from": jury_members[1]['name'], "to": jury_members[0]['name']}] }


    # 5. 라운드 종료 처리 및 6. 최종 상태 변경
    discussion_log.status = "waiting_for_vote"
    discussion_log.turn_number += 1  # 턴 번호를 1 증가시킴
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