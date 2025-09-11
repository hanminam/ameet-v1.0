# src/app/services/report_generator.py

import asyncio
import json
from typing import Dict, Any, List
from datetime import datetime, timedelta
import re

from app.core.config import logger, settings
from app.models.discussion import DiscussionLog, AgentSettings
from app.tools.search import get_stock_price_async, get_economic_data_async
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
import weasyprint
from google.cloud import storage
from app.schemas.report import ReportStructure, ChartRequest # Pydantic 모델을 별도 파일로 관리 (가정)

# --- 신규 AI 에이전트 호출을 위한 보조 함수 ---

async def _run_llm_agent(agent_name: str, prompt_text: str, input_data: Dict, output_schema=None) -> Any:
    """특정 AI 에이전트를 호출하는 범용 함수"""
    agent_setting = await AgentSettings.find_one(
        AgentSettings.name == agent_name, 
        AgentSettings.status == "active"
    )
    if not agent_setting:
        raise ValueError(f"'{agent_name}' 에이전트를 DB에서 찾을 수 없습니다.")

    # 모델 및 체인 구성
    llm = ChatGoogleGenerativeAI(model=agent_setting.config.model, temperature=agent_setting.config.temperature)
    
    # MIME 타입이 필요한 모델(e.g., JSON 출력용)을 위한 설정
    if "json" in agent_setting.config.prompt.lower():
         llm = ChatGoogleGenerativeAI(
            model=agent_setting.config.model,
            temperature=agent_setting.config.temperature,
            model_kwargs={"response_mime_type": "application/json"}
        )

    chain = ChatPromptTemplate.from_messages([("system", agent_setting.config.prompt), ("human", "{input}")])
    
    final_chain = chain | llm.with_structured_output(output_schema) if output_schema else chain | llm

    # LLM 호출
    response = await final_chain.ainvoke({"input": prompt_text.format(**input_data)})
    
    # structured output이 아닐 경우 content를 반환
    return response if output_schema else response.content

# --- 보고서 생성 파이프라인의 각 단계 ---

async def _plan_report_structure(discussion_log: DiscussionLog) -> ReportStructure:
    """[신규] Report Component Planner를 호출하여 보고서의 전체 구조와 차트 요청서를 기획합니다."""
    logger.info(f"--- [Report-Step1] Running Report Component Planner for {discussion_log.discussion_id} ---")
    
    transcript_str = "\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript])
    
    prompt = "Topic: {topic}\n\nFull Transcript:\n{transcript}"
    input_data = {"topic": discussion_log.topic, "transcript": transcript_str}
    
    # `ReportStructure` Pydantic 모델을 기준으로 구조화된 출력을 요청
    report_plan = await _run_llm_agent("Report Component Planner", prompt, input_data, output_schema=ReportStructure)
    return report_plan

async def _create_charts_data(chart_requests: List[ChartRequest], discussion_id: str) -> List[Dict]:
    """'차트 요청서' 목록을 받아 Chart.js용 데이터 목록을 반환합니다."""
    charts_data = []
    if not chart_requests:
        return charts_data
        
    for request in chart_requests:
        try:
            # 1. Ticker/ID 해석
            logger.info(f"--- [Chart-Step1] Ticker/ID resolving for: {request.required_data_description} ---")
            resolver_prompt = "Find the ticker/ID for: {description}"
            resolver_input = {"description": request.required_data_description}
            # Resolver는 JSON 응답이 필요하므로 output_schema를 사용하지 않고 파싱
            resolver_result_str = await _run_llm_agent("Financial Data Ticker/ID Resolver", resolver_prompt, resolver_input)
            resolver_result = json.loads(resolver_result_str)

            # 2. 데이터 조회
            logger.info(f"--- [Chart-Step2] Fetching data for ID: {resolver_result.get('id')} ---")
            raw_data = None
            if resolver_result.get('type') == 'stock':
                end_date = datetime.now()
                start_date = end_date - timedelta(days=180)
                raw_data = await get_stock_price_async(resolver_result['id'], start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
            elif resolver_result.get('type') == 'economic':
                raw_data = await get_economic_data_async(resolver_result['id'])
            
            if not raw_data: continue

            # 3. Chart.js 데이터 합성
            logger.info(f"--- [Chart-Step3] Synthesizing Chart.js data ---")
            synthesizer_prompt = "Chart Request: {request}\n\nRaw Data: {raw_data}"
            synthesizer_input = {"request": request.model_dump_json(), "raw_data": json.dumps(raw_data, default=str)}
            chart_js_str = await _run_llm_agent("Chart Data Synthesizer", synthesizer_prompt, synthesizer_input)
            chart_js_json = json.loads(chart_js_str)

            if "error" not in chart_js_json:
                charts_data.append({
                    "chart_title": request.chart_title,
                    "chart_js_data": chart_js_json
                })
        except Exception as e:
            logger.error(f"Chart generation failed for request {request.chart_title}: {e}", exc_info=True)
            
    return charts_data

async def _generate_final_html(structured_data: Dict, discussion_id: str) -> str:
    """[개선] Infographic Report Agent를 호출하여 최종 정적 HTML을 생성합니다."""
    logger.info(f"--- [Report-Step3] Running Infographic Report Agent for {discussion_id} ---")

    # 프롬프트에 구조화된 데이터를 JSON 형태로 주입
    prompt = "Here is the structured data for the report:\n\n{json_data}"
    input_data = {"json_data": json.dumps(structured_data, ensure_ascii=False, indent=2)}
    
    # LLM으로부터 순수 HTML 문자열을 받음
    html_content = await _run_llm_agent("Infographic Report Agent", prompt, input_data)
    
    # LLM 응답에 포함될 수 있는 마크다운 코드 블록 제거
    match = re.search(r"```(html)?\s*(<!DOCTYPE html>.*)```", html_content, re.DOTALL)
    return match.group(2).strip() if match else html_content.strip()

async def _upload_to_gcs(pdf_bytes: bytes, discussion_id: str) -> str:
    """생성된 PDF를 Google Cloud Storage에 업로드하고 공개 URL을 반환합니다."""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(settings.GCS_BUCKET_NAME)
        blob_name = f"reports/{discussion_id}.pdf"
        blob = bucket.blob(blob_name)
        
        blob.upload_from_string(pdf_bytes, content_type='application/pdf')
        logger.info(f"--- [Report BG Task] PDF uploaded to GCS bucket '{settings.GCS_BUCKET_NAME}'. ---")
        return blob.public_url
    except Exception as e:
        logger.error(f"!!! GCS Upload Failed: {e}", exc_info=True)
        return ""

# --- 메인 보고서 생성 파이프라인 ---

async def generate_report_background(discussion_id: str):
    """[메인 오케스트레이터] 보고서 생성 전체 파이프라인을 실행합니다."""
    logger.info(f"--- [Report BG Task] Started for Discussion ID: {discussion_id} ---")
    discussion_log = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    if not discussion_log:
        logger.error(f"!!! DiscussionLog not found for ID: {discussion_id}")
        return

    try:
        # 1단계: 보고서 구조 및 차트 요청 기획
        report_plan = await _plan_report_structure(discussion_log)
        structured_data = report_plan.model_dump()

        # 2단계: 차트 데이터 생성
        charts_data = await _create_charts_data(report_plan.chart_requests, discussion_id)
        structured_data['charts_data'] = charts_data

        # 3단계: 최종 HTML 본문 생성
        report_body_html = await _generate_final_html(structured_data, discussion_id)

        # 4단계: 참여자 발언 전문 HTML 섹션 생성 (아이콘 문제 해결)
        participant_map = {p['name']: p for p in discussion_log.participants}
        transcript_html_items = []
        regular_message_count = 0
        
        for turn in discussion_log.transcript:
            agent_name = turn.get("agent_name")
            if agent_name in ["SNR 전문가", "정보 검증부", "구분선", "사회자"]:
                continue

            icon = participant_map.get(agent_name, {}).get('icon', '🤖')
            alignment_class = "flex-row-reverse text-right" if regular_message_count % 2 != 0 else "text-left"
            bg_class = "bg-blue-100" if regular_message_count % 2 != 0 else "bg-slate-100"
            message_html = turn.get("message", "").replace('\n', '<br>')
            
            transcript_html_items.append(f"""
            <div class="transcript-turn flex items-start gap-3 my-4 {alignment_class}">
                <div class="w-10 h-10 rounded-full bg-slate-200 flex-shrink-0 flex items-center justify-center text-xl">{icon}</div>
                <div class="flex-1">
                    <p class="text-sm font-bold text-slate-800">{agent_name}</p>
                    <div class="mt-1 p-3 rounded-lg inline-block {bg_class}">{message_html}</div>
                </div>
            </div>""")
            regular_message_count += 1
            
        full_transcript_section = f"""
        <section class="mb-12">
            <h2 class="text-3xl font-bold text-gray-800 mb-6 text-center border-b pb-4">V. 참여자 발언 전문</h2>
            <div class="transcript-container space-y-4">{''.join(transcript_html_items)}</div>
        </section>"""

        # 5단계: HTML 본문과 발언 전문 결합
        final_report_html = report_body_html.replace("</body>", f"{full_transcript_section}</body>") if "</body>" in report_body_html else report_body_html + full_transcript_section
        
        # 6단계: PDF 변환 및 GCS 업로드
        pdf_bytes = weasyprint.HTML(string=final_report_html).write_pdf()
        pdf_url = await _upload_to_gcs(pdf_bytes, discussion_id)

        # 7단계: DB 업데이트
        discussion_log.report_html = final_report_html
        discussion_log.pdf_url = pdf_url
        discussion_log.status = "completed"
        await discussion_log.save()
        logger.info(f"--- [Report BG Task] Successfully completed for {discussion_id} ---")

    except Exception as e:
        logger.error(f"!!! [Report BG Task] FAILED for ID: {discussion_id}. Error: {e}", exc_info=True)
        discussion_log.status = "failed"
        await discussion_log.save()