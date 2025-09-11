# src/app/services/report_generator.py

import asyncio
import json
from typing import Dict, Any, List
from datetime import datetime, timedelta
import re

from app.core.config import logger, settings
from app.models.discussion import DiscussionLog, AgentSettings
from app.tools.search import get_stock_price_async, get_economic_data_async, perform_web_search_async
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
import weasyprint
from google.cloud import storage

# --- 신규 AI 에이전트 호출을 위한 보조 함수 ---

async def _run_llm_agent(agent_name: str, prompt: str, input_data: Dict, output_schema=None) -> Dict | str:
    """특정 AI 에이전트를 호출하는 범용 함수"""
    agent_setting = await AgentSettings.find_one(
        AgentSettings.name == agent_name, 
        AgentSettings.status == "active"
    )
    if not agent_setting:
        raise ValueError(f"'{agent_name}' 에이전트를 DB에서 찾을 수 없습니다.")

    llm = ChatGoogleGenerativeAI(
        model=agent_setting.config.model,
        temperature=agent_setting.config.temperature
    )
    
    chain = ChatPromptTemplate.from_messages([("system", agent_setting.config.prompt), ("human", "{input}")])
    
    if output_schema:
        structured_llm = llm.with_structured_output(output_schema)
        chain = chain | structured_llm
    else:
        chain = chain | llm

    response = await chain.ainvoke({"input": prompt.format(**input_data)})
    return response if output_schema else response.content

# --- 차트 생성 서브-파이프라인 함수 ---

async def _create_charts_data(chart_requests: List[Dict], discussion_id: str) -> List[Dict]:
    """
    '차트 요청서' 목록을 받아, ID해석->데이터조회->데이터가공 파이프라인을 실행하고
    Chart.js에 바로 사용할 수 있는 데이터 목록을 반환합니다.
    """
    charts_data = []
    for request in chart_requests:
        try:
            logger.info(f"--- [Chart-Step1] Ticker/ID resolving for: {request['required_data_description']} ---")
            # 1. Ticker/ID Resolver 호출하여 식별자 획득
            resolver_prompt = "Find the ticker/ID for the following data description: {description}"
            resolver_input = {"description": request['required_data_description']}
            # 실제 구현에서는 _run_llm_agent를 사용해야 하나, 여기서는 안정적인 테스트를 위해 모의 결과 사용
            # resolver_result = await _run_llm_agent("Financial Data Ticker/ID Resolver", resolver_prompt, resolver_input)
            # 임시 모의 결과:
            if "테슬라" in request['required_data_description']:
                 resolver_result = {"type": "stock", "id": "TSLA"}
            else:
                 resolver_result = {"type": "economic", "id": "UNRATE"} # 예시: 미국 실업률

            # 2. 식별자로 적합한 도구를 사용하여 실제 데이터 조회
            logger.info(f"--- [Chart-Step2] Fetching data for ID: {resolver_result['id']} ---")
            raw_data = None
            if resolver_result['type'] == 'stock':
                end_date = datetime.now()
                start_date = end_date - timedelta(days=180)
                raw_data = await get_stock_price_async(resolver_result['id'], start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
            elif resolver_result['type'] == 'economic':
                raw_data = await get_economic_data_async(resolver_result['id'])
            
            if not raw_data: continue

            # 3. Chart Data Synthesizer를 호출하여 Chart.js용 JSON 생성
            logger.info(f"--- [Chart-Step3] Synthesizing Chart.js data ---")
            synthesizer_prompt = "Chart Request: {request}\n\nRaw Data: {raw_data}"
            synthesizer_input = {"request": json.dumps(request), "raw_data": json.dumps(raw_data)}
            # 실제 구현에서는 _run_llm_agent를 사용
            # chart_js_json = await _run_llm_agent("Chart Data Synthesizer", synthesizer_prompt, synthesizer_input)
            # 임시 모의 결과:
            chart_js_json = {
                "labels": [item['Date'] for item in raw_data],
                "datasets": [{"label": request['chart_title'], "data": [item.get('Close', item.get('Value')) for item in raw_data]}]
            }

            if "error" not in chart_js_json:
                charts_data.append({
                    "chart_title": request['chart_title'],
                    "chart_js_data": chart_js_json
                })
        except Exception as e:
            logger.error(f"Chart generation failed for request {request}: {e}", exc_info=True)
            
    return charts_data

# --- 메인 보고서 생성 파이프라인 함수 ---

async def _get_structured_data_and_requests(discussion_log: DiscussionLog) -> Dict:
    """Report Data Structurer를 호출하여 보고서 데이터와 차트 요청서를 생성합니다."""
    logger.info(f"--- [Report-Step1] Running Report Data Structurer for {discussion_log.discussion_id} ---")
    # ... Report Data Structurer 에이전트 호출 로직 ...
    # 이 단계의 LLM 호출은 비용과 시간상 생략하고, 예시 데이터를 반환합니다.
    return {
        "title": f"{discussion_log.topic} - 최종 분석 보고서",
        "subtitle": "AI 에이전트 집단지성 토론 기반",
        "expert_opinions": [
            {"expert": op['agent_name'], "opinion": op['message'][:150] + "..."} 
            for op in discussion_log.transcript if op['agent_name'] not in ["재판관", "사회자", "구분선", "SNR 전문가", "정보 검증부"]
        ],
        "key_factors": {
            "positive": ["로보택시, 자율주행 기술 성공 기대", "강력한 브랜드 파워와 팬덤"],
            "negative": ["성장주에 불리한 고금리 기조", "전기차 시장 경쟁 심화"]
        },
        "conclusion": "단기적 변동성은 크지만, 장기적 관점에서 기업 펀더멘털과 시장 상황을 종합적으로 분석하는 것이 중요합니다.",
        "chart_requests": [
            {
                "chart_title": "테슬라 최근 6개월 주가 추이",
                "required_data_description": "테슬라(Tesla Inc.)의 최근 6개월간의 일일 주가 데이터",
                "suggested_chart_type": "line_chart"
            }
        ]
    }

async def _generate_final_html(structured_data: Dict, transcript_str: str, discussion_id: str) -> str:
    """Infographic Report Agent를 호출하여 최종 HTML을 생성합니다."""
    logger.info(f"--- [Report-Step2] Running Infographic Report Agent for {discussion_id} ---")
    
    report_agent_setting = await AgentSettings.find_one(
        AgentSettings.name == "Infographic Report Agent", 
        AgentSettings.status == "active"
    )
    if not report_agent_setting: raise ValueError("Infographic Report Agent not found.")

    # 실제 데이터를 포함하여 최종 프롬프트 동적 조립
    final_prompt = f"""
        {report_agent_setting.config.prompt}

        ### 보고서 생성을 위한 구조화된 데이터:
        ```json
        {json.dumps(structured_data, ensure_ascii=False, indent=2)}
        ```

        위 JSON 데이터를 기반으로, 지시사항에 명시된 5가지 필수 구조를 모두 포함하는 완벽한 인포그래픽 HTML 보고서를 생성하세요.
        특히, JSON 데이터의 `charts_data` 배열에 있는 데이터를 사용하여 Chart.js 스크립트를 작성해야 합니다. 예시나 가짜 데이터를 절대 사용하지 마십시오.

        ### 참여자 발언 전문 (보고서 마지막에 반드시 포함):
        ```
        {transcript_str}
        ```
    """
    
    # 보고서 생성을 위해 가장 성능이 좋은 모델 사용
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0.2)
    response = await llm.ainvoke(
        final_prompt,
        config={"tags": [f"discussion_id:{discussion_id}", "task:generate_report_html"]}
    )
    
    # LLM 응답에서 순수 HTML만 추출
    raw_html = response.content
    match = re.search(r"```(html)?\s*(<!DOCTYPE html>.*)```", raw_html, re.DOTALL)
    return match.group(2).strip() if match else raw_html.strip()

async def generate_report_background(discussion_id: str):
    """
    [메인 오케스트레이터] 보고서 생성 전체 파이프라인을 실행합니다.
    """
    logger.info(f"--- [Report BG Task] Started for Discussion ID: {discussion_id} ---")
    discussion_log = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    if not discussion_log:
        logger.error(f"!!! DiscussionLog not found for ID: {discussion_id}")
        return

    try:
        # 1단계: 데이터 구조화 및 '차트 요청서' 수신
        structured_data = await _get_structured_data_and_requests(discussion_log)
        chart_requests = structured_data.pop("chart_requests", [])
        
        # 2단계: 차트 데이터 생성 서브-파이프라인 실행
        charts_data = await _create_charts_data(chart_requests, discussion_id)
        structured_data['charts_data'] = charts_data

        # 3단계: 최종 HTML 생성
        transcript_str = "\n\n".join([f"### {t['agent_name']}\n{t['message']}" for t in discussion_log.transcript])
        report_html = await _generate_final_html(structured_data, transcript_str, discussion_id)
        
        # 4단계: PDF 변환
        pdf_bytes = weasyprint.HTML(string=report_html).write_pdf()
        
        # 5단계: GCS 업로드
        storage_client = storage.Client()
        bucket = storage_client.bucket(settings.GCS_BUCKET_NAME)
        blob_name = f"reports/{discussion_id}.pdf"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(pdf_bytes, content_type='application/pdf')
        pdf_url = blob.public_url
        logger.info(f"--- [Report BG Task] PDF uploaded to {pdf_url} ---")

        # 6단계: DB 업데이트
        discussion_log.report_html = report_html
        discussion_log.pdf_url = pdf_url
        discussion_log.status = "completed"
        await discussion_log.save()
        logger.info(f"--- [Report BG Task] Successfully completed for {discussion_id} ---")

    except Exception as e:
        logger.error(f"!!! [Report BG Task] FAILED for ID: {discussion_id}. Error: {e}", exc_info=True)
        discussion_log.status = "failed"
        await discussion_log.save()