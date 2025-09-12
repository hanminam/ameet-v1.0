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
    """ AI 실패에 대비한 안전장치를 추가하여 안정성을 극대화합니다."""
    logger.info(f"--- [Report-Step1.1] Running Report Outline Generator for {discussion_log.discussion_id} ---")
    
    transcript_str = "\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript])
    prompt1 = "Topic: {topic}\n\nFull Transcript:\n{transcript}"
    input_data1 = {"topic": discussion_log.topic, "transcript": transcript_str}
    
    # 1. 창의적인 개요와 차트 '아이디어' 생성
    outline_plan = await _run_llm_agent("Report Outline Generator", prompt1, input_data1, output_schema=ReportOutline)

    # [로그 추가] 첫 번째 AI의 결과물을 직접 확인
    logger.info(f"--- [Report-Debug] Outline Generator's Chart Ideas: {outline_plan.chart_ideas if outline_plan else 'None'} ---")

    if not outline_plan:
        logger.error("!!! [Report-Step1.1 FAILED] Report Outline Generator returned None. Creating a minimal fallback report. ---")
        # AI가 완전히 실패하면, 제목만 있는 최소한의 보고서 구조를 생성
        return ReportStructure(title=f"{discussion_log.topic} - 분석 보고서")

    # AI가 제목을 생성하지 못한 경우, 토론 주제를 기반으로 기본 제목을 생성
    if not outline_plan.title:
        outline_plan.title = f"{discussion_log.topic} - 최종 분석 보고서"
        logger.warning(f"--- [Report-Step1.1] Outline Generator failed to provide a title. Using default: '{outline_plan.title}' ---")
    
    if not outline_plan.chart_ideas:
        logger.warning("--- [Report-Step1.1] Outline Generator did not produce chart ideas. Proceeding without charts. ---")
        # 차트 아이디어가 없어도 보고서의 다른 부분은 유효하므로 그대로 사용
        return ReportStructure(**outline_plan.model_dump())

    logger.info(f"--- [Report-Step1.2] Running Chart Plan Validator for {len(outline_plan.chart_ideas)} ideas ---")
    
    # 2. 아이디어를 바탕으로 '실행 가능한' 차트 계획만 필터링/생성
    current_date_str = datetime.now().strftime('%Y-%m-%d')
    prompt2 = "Current Date: {current_date}\n\nChart Ideas:\n{chart_ideas}"
    input_data2 = {
        "current_date": current_date_str,
        "chart_ideas": json.dumps(outline_plan.chart_ideas, ensure_ascii=False)
    }
    
    validated_plan = await _run_llm_agent("Chart Plan Validator", prompt2, input_data2, output_schema=ValidatedChartPlan)

    # [로그 추가] 두 번째 AI가 변환에 성공한 최종 계획을 확인
    logger.info(f"--- [Report-Debug] Chart Plan Validator's Final Requests: {validated_plan.chart_requests if validated_plan else 'None'} ---")

    # 3. 두 결과를 조합하여 최종 ReportStructure 객체 생성
    final_report_structure = ReportStructure(
        title=outline_plan.title,
        subtitle=outline_plan.subtitle,
        expert_opinions=outline_plan.expert_opinions,
        key_factors=outline_plan.key_factors,
        conclusion=outline_plan.conclusion,
        chart_requests=validated_plan.chart_requests if validated_plan else []
    )
    
    return final_report_structure

async def _create_charts_data(chart_requests: List[ChartRequest], discussion_id: str) -> List[Dict]:
    """[최종 버전] AI 호출 없이 Python 코드로 직접 차트 데이터를 생성하여 안정성을 확보합니다."""
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
        # 1단계: 보고서 텍스트 개요 및 차트 대상 '개체' 목록 생성
        transcript_str = "\n".join([f"{t['agent_name']}: {t['message']}" for t in discussion_log.transcript])
        outline_plan = await _run_llm_agent(
            "Report Outline Generator",
            "Topic: {topic}\n\nFull Transcript:\n{transcript}",
            {"topic": discussion_log.topic, "transcript": transcript_str},
            output_schema=ReportOutline
        )
        if not outline_plan:
            raise ValueError("Report Outline Generator failed to produce an outline.")
        
        structured_data = outline_plan.model_dump(exclude={'chart_worthy_entities'}) # 최종 보고서에는 엔티티 목록 불필요

        # 2단계 : 지능형 차트 계획 생성 파이프라인 호출
        chart_requests = await _create_chart_requests_intelligently(discussion_log, outline_plan)

        # 3단계 : 차트 데이터 생성 (이제 안정적으로 계획을 전달받음)
        charts_data = await _create_charts_data(chart_requests, discussion_id)
        structured_data['charts_data'] = charts_data

        # 4단계 : 최종 HTML 본문 생성
        report_body_html = await _generate_final_html(structured_data, discussion_id)

        # 5단계 : 참여자 발언 전문 HTML 섹션 생성
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

        # 6단계 (기존): HTML 본문과 발언 전문 결합
        final_report_html = report_body_html.replace("</body>", f"{full_transcript_section}</body>") if "</body>" in report_body_html else report_body_html + full_transcript_section
        
        # 7단계 (기존): PDF 변환 및 GCS 업로드
        pdf_bytes = weasyprint.HTML(string=final_report_html).write_pdf()
        pdf_url = await _upload_to_gcs(pdf_bytes, discussion_id)

        # 8단계 (기존): DB 업데이트
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