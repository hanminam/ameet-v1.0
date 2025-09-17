# src/app/services/report_generator.py

import asyncio
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import re

from app.core.config import logger, settings
from app.models.discussion import DiscussionLog, AgentSettings
from app.tools.search import get_stock_price_async, get_economic_data_async
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
import weasyprint
from google.cloud import storage
from app.schemas.report import ReportStructure, ChartRequest, ResolverOutput, ReportOutline, ValidatedChartPlan
from pydantic import BaseModel, ValidationError

class ChartRelevance(BaseModel):
    is_chart_relevant: bool

class ChartParameters(BaseModel):
    chart_type: str
    chart_title: str
    start_date: str
    end_date: str

# --- 데이터 사전 처리 헬퍼 함수 ---
def _preprocess_data_for_synthesizer(raw_data: List[Dict], data_type: str) -> List[Dict]:
    """Chart Data Synthesizer에 보내기 전에 원본 데이터를 최소한의 형태로 가공합니다."""
    if not raw_data:
        return []

    processed_data = []
    if data_type == 'stock':
        for d in raw_data:
            if 'Date' in d and 'Close' in d:
                processed_data.append({"Date": d['Date'], "Close": d['Close']})
    elif data_type == 'economic':
        for d in raw_data:
            if 'Date' in d and 'Value' in d:
                processed_data.append({"Date": d['Date'], "Value": d['Value']})
    
    return processed_data[-365:]

async def _create_chart_requests_intelligently(discussion_log: DiscussionLog, outline: ReportOutline) -> List[ChartRequest]:
    """
    지능형 차트 생성 파이프라인
    """
    logger.info(f"--- [Report-Chart-Pipe] Starting intelligent chart pipeline for {discussion_log.discussion_id} ---")
    
    # 1단계: 차트 생성 필요성 판단
    relevance_check = await _run_llm_agent(
        "Chart Relevance Classifier",
        "Topic: {topic}\n\nTranscript:\n{transcript}",
        {"topic": discussion_log.topic, "transcript": "\n".join(t['message'] for t in discussion_log.transcript)},
        output_schema=ChartRelevance
    )
    if not relevance_check or not relevance_check.is_chart_relevant:
        logger.info("--- [Report-Chart-Pipe] Chart relevance check is FALSE. Skipping chart generation. ---")
        return []

    # 2단계: 차트화할 핵심 개체(Entity) 목록 사용 (ReportOutlineGenerator가 생성)
    entities = outline.chart_worthy_entities
    if not entities:
        logger.info("--- [Report-Chart-Pipe] No chart-worthy entities found. Skipping. ---")
        return []
    
    logger.info(f"--- [Report-Chart-Pipe] Found entities: {entities} ---")

    # 3단계 & 4단계: 각 개체에 대해 ID 해석 및 파라미터 생성을 병렬 처리
    tasks = []
    for entity in entities:
        tasks.append(_resolve_and_plan_chart(entity))
        
    chart_plans = await asyncio.gather(*tasks)
    
    # 최종적으로 유효한 ChartRequest만 필터링하여 반환
    final_requests = [plan for plan in chart_plans if plan]
    logger.info(f"--- [Report-Chart-Pipe] Pipeline finished. Generated {len(final_requests)} valid chart requests. ---")
    return final_requests


async def _resolve_and_plan_chart(entity: str) -> Optional[ChartRequest]:
    """
    단일 개체에 대한 ID 해석 및 계획 생성을 처리
    """
    try:
        # 3단계: Ticker/ID 해석
        resolver_prompt = "Find the ticker or series ID for the following entity: {entity}"
        resolved_output = await _run_llm_agent(
            "Financial Data Ticker/ID Resolver",
            resolver_prompt,
            {"entity": entity},
            output_schema=ResolverOutput
        )
        if not resolved_output: return None
        
        logger.info(f"--- [Chart-Pipe-Detail] Resolved '{entity}' -> ID: '{resolved_output.id}' ({resolved_output.type})")

        # 4단계: 차트 파라미터 생성
        param_prompt = "Entity to chart: '{entity}'\nResolved ID: '{resolved_id}'"
        params = await _run_llm_agent(
            "Chart Parameter Generator",
            param_prompt,
            {"entity": entity, "resolved_id": resolved_output.id},
            output_schema=ChartParameters
        )
        if not params: return None
        
        logger.info(f"--- [Chart-Pipe-Detail] Generated params for '{entity}': {params.chart_type}, {params.start_date} to {params.end_date}")

        # 5단계: 최종 계획 조립
        tool_map = {"stock": "get_stock_price", "economic": "get_economic_data"}
        tool_args_map = {"stock": "ticker", "economic": "series_id"}

        return ChartRequest(
            chart_title=params.chart_title,
            tool_name=tool_map.get(resolved_output.type),
            tool_args={
                tool_args_map.get(resolved_output.type): resolved_output.id,
                "start_date": params.start_date,
                "end_date": params.end_date
            }
        )
    except Exception as e:
        logger.error(f"--- [Chart-Pipe-Error] Failed to process entity '{entity}': {e}", exc_info=True)
        return None

# --- AI 에이전트 호출을 위한 보조 함수 ---

async def _run_llm_agent(agent_name: str, prompt_text: str, input_data: Dict, output_schema=None) -> Any:
    """ 특정 AI 에이전트를 호출하는 범용 함수"""
    agent_setting = await AgentSettings.find_one(
        AgentSettings.name == agent_name, 
        AgentSettings.status == "active"
    )
    if not agent_setting:
        raise ValueError(f"'{agent_name}' 에이전트를 DB에서 찾을 수 없습니다.")

    # llm 인스턴스 생성을 한번만 하도록 단순화
    llm = ChatGoogleGenerativeAI(
        model=agent_setting.config.model,
        temperature=agent_setting.config.temperature
    )
    
    chain = ChatPromptTemplate.from_messages([("system", agent_setting.config.prompt), ("human", "{input}")])
    
    # output_schema가 제공되면 .with_structured_output()을 사용, 아니면 일반 LLM 호출
    try:
        final_chain = chain | llm.with_structured_output(output_schema) if output_schema else chain | llm
        response = await final_chain.ainvoke({"input": prompt_text.format(**input_data)})
        return response if output_schema else response.content
        
    except ValidationError as e:
        # [핵심] 오류 발생 시, 어떤 에이전트에서 어떤 상세 오류가 났는지 명확하게 로깅합니다.
        logger.error(f"--- [Pydantic ValidationError] Agent '{agent_name}' failed validation. ---")
        logger.error(f"Detailed Error: {e}")
        # 오류가 발생했음을 알리기 위해 None을 반환하거나 예외를 다시 발생시킬 수 있습니다.
        raise e 
    except Exception as e:
        logger.error(f"--- [LLM Agent Error] An unexpected error occurred in agent '{agent_name}': {e}", exc_info=True)
        raise e

# --- 보고서 생성 파이프라인의 각 단계 ---

async def _plan_report_structure(discussion_log: DiscussionLog) -> ReportStructure:
    """ 단일 AI 에이전트('Report Component Planner')를 호출하여 보고서의 전체 구조와
    실행 가능한 차트 요청 목록을 한 번에 생성합니다. """
    logger.info(f"--- [Report-Step1] Running Unified Report Component Planner for {discussion_log.discussion_id} ---")

    transcript_str = "\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript])
    current_date_str = datetime.now().strftime('%Y-%m-%d')

    prompt = (
        "Based on the following discussion topic and transcript, generate a complete and structured report plan. "
        "The plan must include a title, subtitle, expert opinions, key factors, a final conclusion, "
        "and a list of specific, actionable chart requests ready for tool execution.\n\n"
        "Current Date: {current_date}\n\n"
        "Topic: {topic}\n\n"
        "Full Transcript:\n{transcript}"
    )

    input_data = {
        "current_date": current_date_str,
        "topic": discussion_log.topic,
        "transcript": transcript_str
    }

    # 'Report Component Planner'를 한 번만 호출하여 모든 구조를 생성
    report_plan = await _run_llm_agent(
        "Report Component Planner",
        prompt,
        input_data,
        output_schema=ReportStructure
    )

    if not report_plan:
        logger.error("!!! [Report-Step1 FAILED] Report Component Planner returned None. Creating a fallback report.")
        # ReportStructure의 title이 Optional이 되었으므로, 빈 객체를 만들 수 없습니다.
        # 따라서 여기서 기본 제목을 가진 객체를 직접 생성하여 반환합니다.
        return ReportStructure(title=f"{discussion_log.topic} - 분석 보고서", chart_requests=[])

    # AI가 제목을 생성하지 못한 경우, 토론 주제를 기반으로 기본 제목을 설정 (안전장치)
    if not report_plan.title:
        logger.warning("--- [Report Fallback] AI failed to generate a title. Using default title. ---")
        report_plan.title = f"{discussion_log.topic} - 최종 분석 보고서"

    return report_plan

async def _create_charts_data(chart_requests: List[ChartRequest], discussion_id: str) -> List[Dict]:
    """ AI 호출 없이 Python 코드로 직접 차트 데이터를 생성하여 안정성을 확보합니다."""
    charts_data = []
    if not chart_requests:
        return charts_data
        
    for request in chart_requests:
        try:
            tool_name = request.tool_name
            tool_args = request.tool_args
            
            logger.info(f"--- [Chart-Step2] Executing tool '{tool_name}' with args: {tool_args} ---")
            raw_data = None

            # 1. 계획에 명시된 도구 실행
            if tool_name == 'get_stock_price':
                raw_data = await get_stock_price_async(**tool_args)
            elif tool_name == 'get_economic_data':
                raw_data = await get_economic_data_async(**tool_args)

            # 2. 데이터 조회 결과 검증
            if not raw_data:
                logger.warning(f"--- [Chart-Step2 FAILED] No data returned for tool '{tool_name}'. Skipping chart. ---")
                continue

            # --- ▼▼▼ [핵심 수정] AI(Synthesizer) 호출 대신 Python 코드로 직접 데이터 변환 ▼▼▼ ---
            logger.info(f"--- [Chart-Step3] Transforming data to Chart.js format using Python code. ---")
            
            labels = []
            dataset_data = []
            label_name = ""

            if tool_name == 'get_stock_price':
                labels = [d['Date'] for d in raw_data]
                dataset_data = [d.get('Close') for d in raw_data]
                label_name = tool_args.get('ticker', 'Stock Price')
            elif tool_name == 'get_economic_data':
                labels = [d['Date'] for d in raw_data]
                dataset_data = [d.get('Value') for d in raw_data]
                label_name = tool_args.get('series_id', 'Economic Data')
            
            # Chart.js가 요구하는 최종 JSON 형식으로 조립
            chart_js_data = {
                "labels": labels,
                "datasets": [{
                    "label": label_name,
                    "data": dataset_data,
                    "fill": False,
                    "borderColor": 'rgb(75, 192, 192)',
                    "tension": 0.1
                }]
            }
            
            charts_data.append({
                "chart_title": request.chart_title,
                "chart_js_data": chart_js_data
            })
            # --- ▲▲▲ 수정 완료 ▲▲▲ ---

        except Exception as e:
            logger.error(f"Chart generation failed for request '{request.chart_title}': {e}", exc_info=True)
            
    return charts_data

async def _generate_final_html(structured_data: Dict, discussion_id: str) -> str:
    """ Infographic Report Agent를 호출하여 최종 정적 HTML을 생성합니다."""
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
    """[메인 오케스트레이터] 새로운 파이프라인을 적용한 보고서 생성 전체 흐름"""
    logger.info(f"--- [Report BG Task] Started for Discussion ID: {discussion_id} ---")
    discussion_log = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    if not discussion_log:
        logger.error(f"!!! DiscussionLog not found for ID: {discussion_id}")
        return

    try:
        # 1단계: [통합] 보고서의 텍스트 구조와 실행 가능한 차트 계획을 한 번에 생성
        report_plan = await _plan_report_structure(discussion_log)
        if not report_plan:
            raise ValueError("Report planner failed to produce a valid structure.")

        # 2단계: 생성된 계획에 따라 필요한 차트 데이터를 외부 API에서 조회
        charts_data = await _create_charts_data(report_plan.chart_requests, discussion_id)

        # 3단계: 최종 보고서 생성을 위한 데이터 조립
        # (차트 데이터를 포함한 모든 계획을 딕셔너리로 변환)
        structured_data = report_plan.model_dump()
        structured_data['charts_data'] = charts_data

        # 4단계 : 조립된 데이터를 바탕으로 최종 HTML 본문 생성
        report_body_html = await _generate_final_html(structured_data, discussion_id)

        # 5단계 : 토론 참여자들의 발언 전문을 담을 HTML 섹션 생성
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
            
        transcript_html_str = "\n".join(transcript_html_items)
        full_transcript_section = f"""
        <section class="mb-12">
            <div class="bg-white p-6 rounded-xl shadow-md">
                <h2 class="text-3xl font-bold text-gray-800 mb-6 text-center border-b pb-4">V. 참여자 발언 전문</h2>
                <div class="transcript-container space-y-4">{transcript_html_str}</div>
            </div>
        </section>"""

        # 6단계: AI가 생성한 보고서 본문과 발언 전문 섹션을 결합
        final_report_html = report_body_html.replace("</body>", f"{full_transcript_section}</body>") if "</body>" in report_body_html else report_body_html + full_transcript_section
        
        # 7단계: 최종 HTML을 PDF로 변환하고 Google Cloud Storage에 업로드
        pdf_bytes = weasyprint.HTML(string=final_report_html).write_pdf()
        pdf_url = await _upload_to_gcs(pdf_bytes, discussion_id)

        # 8단계: 생성된 보고서 정보와 URL을 데이터베이스에 저장하고 상태를 'completed'로 변경
        discussion_log.report_html = final_report_html
        discussion_log.pdf_url = pdf_url
        discussion_log.status = "completed"
        await discussion_log.save()
        logger.info(f"--- [Report BG Task] Successfully completed for {discussion_id} ---")

    except Exception as e:
        logger.error(f"!!! [Report BG Task] FAILED for ID: {discussion_id}. Error: {e}", exc_info=True)
        if discussion_log:
            discussion_log.status = "failed"
            await discussion_log.save()