# src/app/services/discussion_flow.py
# 미래에 구현될 복잡한 토론 로직을 임시로 대체하는 '기능적인 목업(Functional Mock)' 

import asyncio
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime

from app.schemas.orchestration import DebateTeam
from app.models.discussion import AgentSettings, DiscussionLog
from app.core.config import logger

async def _run_single_agent_turn(agent_config: dict, topic: str, history: str, discussion_id: str) -> str:
    """단일 에이전트의 발언(turn)을 생성합니다. (내부 로직은 이전과 동일)"""
    agent_name = agent_config.get("name", "Unknown Agent")
    logger.info(f"--- [Flow] Running turn for agent: {agent_name} (Discussion: {discussion_id}) ---")
    try:
        llm = ChatGoogleGenerativeAI(
            model=agent_config.get("model", "gemini-1.5-flash"),
            temperature=agent_config.get("temperature", 0.2)
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", agent_config.get("prompt", "You are a helpful assistant.")),
            ("human", "주제: {topic}\n\n지금까지의 토론 내용:\n{history}\n\n당신의 의견을 말해주세요.")
        ])
        chain = prompt | llm
        response = await chain.ainvoke(
            {"topic": topic, "history": history},
            config={"tags": [f"discussion_id:{discussion_id}", f"agent_name:{agent_name}"]}
        )
        return response.content
    except Exception as e:
        logger.error(f"--- [Flow Error] Agent '{agent_name}' turn failed: {e} ---")
        return f"({agent_name} 발언 생성 중 오류 발생)"
    
async def execute_turn(discussion_log: DiscussionLog):
    """
    백그라운드에서 단일 토론 턴을 실행하고, 결과를 DB에 기록합니다.
    """
    logger.info(f"--- [BG Task] Executing turn for Discussion ID: {discussion_log.discussion_id} ---")
    
    current_transcript = [f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript]
    history_str = "\n\n".join(current_transcript)
    
    # 1. 현재 토론 상태에 따라 어떤 턴을 실행할지 결정
    if len(discussion_log.transcript) == 0:
        # --- '모두 변론' 턴 실행 ---
        logger.info(f"--- [Flow] Starting Opening Statements for {discussion_log.discussion_id} ---")
        if not history_str:
            history_str = "토론이 시작되었습니다. 각자 의견을 말씀해주세요."

        # participants 필드에서 'jury' 멤버만 가져옴 (judge 제외)
        jury_members = [p for p in discussion_log.participants if p.get('name') != "재판관"]

        for agent_config in jury_members:
            message = await _run_single_agent_turn(
                agent_config, discussion_log.topic, history_str, discussion_log.discussion_id
            )
            
            turn_data = {"agent_name": agent_config['name'], "message": message, "timestamp": datetime.utcnow()}
            discussion_log.transcript.append(turn_data)
            
            # 다음 에이전트를 위해 대화 기록 업데이트
            history_str += f"\n\n{agent_config['name']}: {message}"
            await asyncio.sleep(1) # 약간의 딜레이

        discussion_log.status = "turn_complete" # 턴 완료 상태로 변경
    
    else:
        # --- 다음 턴(예: 1차 토론, 최종 변론 등) 로직이 들어갈 자리 ---
        # MVP에서는 '모두 변론' 후 바로 '완료' 상태로 변경
        logger.info(f"--- [Flow] No more turns defined. Completing discussion {discussion_log.discussion_id} ---")
        discussion_log.status = "completed"
        discussion_log.completed_at = datetime.utcnow()
        discussion_log.report_summary = "모든 변론이 완료되었습니다."

    # 2. 최종 결과를 DB에 저장
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