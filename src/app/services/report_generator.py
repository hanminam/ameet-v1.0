# src/app/services/report_generator.py

from app.core.config import logger
from app.models.discussion import DiscussionLog, AgentSettings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

async def generate_report_background(discussion_id: str):
    """
    백그라운드에서 보고서 생성을 처리하는 메인 함수
    """
    logger.info(f"--- [Report BG Task] Started for Discussion ID: {discussion_id} ---")
    discussion_log = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    
    if not discussion_log:
        logger.error(f"!!! [Report BG Task] DiscussionLog not found for ID: {discussion_id}")
        return

    try:
        # 1. 보고서 생성 에이전트 설정을 DB에서 가져오기
        report_agent_setting = await AgentSettings.find_one(
            AgentSettings.name == "Infographic Report Agent",
            AgentSettings.status == "active"
        )
        if not report_agent_setting:
            raise ValueError("'Infographic Report Agent'를 DB에서 찾을 수 없습니다.")

        # 2. LLM에 전달할 전체 토론 내용 준비
        transcript_str = "\n\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript])
        
        # 증거 자료가 있다면 함께 전달
        evidence_str = ""
        if discussion_log.evidence_briefing:
            web_evidence = "\n".join([f"- {item['summary']} (출처: {item['source']})" for item in discussion_log.evidence_briefing.get('web_evidence', [])])
            file_evidence = "\n".join([f"- {item['summary']} (출처: {item['source']})" for item in discussion_log.evidence_briefing.get('file_evidence', [])])
            evidence_str = f"--- 참고 자료 ---\n웹 검색 요약:\n{web_evidence}\n\n첨부 파일 요약:\n{file_evidence}\n---"

        full_context = f"토론 주제: {discussion_log.topic}\n\n{evidence_str}\n\n--- 토론 대화록 ---\n{transcript_str}"

        # 3. 보고서 생성 LLM 호출
        llm = ChatGoogleGenerativeAI(
            model=report_agent_setting.config.model,
            temperature=report_agent_setting.config.temperature
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", report_agent_setting.config.prompt),
            ("human", "{context}")
        ])
        chain = prompt | llm

        response = await chain.ainvoke(
            {"context": full_context},
            config={"tags": [f"discussion_id:{discussion_id}", "task:generate_report"]}
        )
        
        report_html = response.content

        # 4. 결과물을 DB에 저장하고 상태를 'completed'로 변경
        discussion_log.report_html = report_html
        discussion_log.status = "completed" # 최종 완료 상태
        await discussion_log.save()
        logger.info(f"--- [Report BG Task] Successfully completed for Discussion ID: {discussion_id} ---")

    except Exception as e:
        logger.error(f"!!! [Report BG Task] FAILED for Discussion ID: {discussion_id}. Error: {e}", exc_info=True)
        discussion_log.status = "failed"
        # 실패 시, 간단한 오류 메시지를 보고서 내용으로 저장할 수 있습니다.
        discussion_log.report_html = f"<h1>보고서 생성 실패</h1><p>오류가 발생했습니다: {e}</p>"
        await discussion_log.save()