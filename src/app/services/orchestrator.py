# src/app/services/orchestrator.py

import asyncio
import json
from typing import List, Dict
from fastapi import UploadFile

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.schemas.orchestration import (
    IssueAnalysisReport, 
    CoreEvidenceBriefing, 
    EvidenceItem,
    SelectedJury,
    DebateTeam
)
# 새로 추가된 서비스와 도구를 임포트합니다.
from app.tools.search import perform_web_search
from app.services.document_processor import process_uploaded_file
from app.services.summarizer import summarize_text

# --- 역할 기반 상수 정의 ---
JUDGE_AGENT_NAME = "사회자"
CRITICAL_AGENT_NAME = "비판적 관점"

async def analyze_topic(topic: str) -> IssueAnalysisReport:
    """
    사용자 주제를 입력받아, 저비용/고속 LLM을 통해 
    '쟁점 분석 보고서' JSON을 생성합니다.
    (이전 단계에서 구현한 함수)
    """
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.1)
    structured_llm = llm.with_structured_output(IssueAnalysisReport)
    system_prompt = """
    You are an expert analyst tasked with deconstructing a complex discussion topic into a structured "Issue Analysis Report" in JSON format. Your goal is to provide a clear, structured foundation for a multi-agent debate.
    Based on the user's topic, you must:
    1.  Identify and list the `core_keywords`.
    2.  Formulate 3 to 5 `key_issues` as probing questions, each with a brief `description`.
    3.  List the `anticipated_perspectives` that are likely to emerge during the debate.
    You must only respond with a single, valid JSON object that strictly adheres to the provided schema. Do not include any explanatory text or markdown formatting before or after the JSON object.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Please analyze the following topic: {topic}"),
    ])
    chain = prompt | structured_llm
    print(f"--- [Orchestrator] 1단계: 사건 분석 시작 (주제: {topic}) ---")
    report = await chain.ainvoke({"topic": topic})
    print(f"--- [Orchestrator] 1단계: 사건 분석 완료 ---")
    return report

# --- [신규] 증거 수집 로직 ---
async def gather_evidence(
    report: IssueAnalysisReport, 
    files: List[UploadFile],
    topic: str
) -> CoreEvidenceBriefing:
    """
    분석 보고서와 사용자 파일을 기반으로 '핵심 자료집'을 생성합니다.
    웹 검색과 파일 처리를 병렬로 수행하여 효율성을 높입니다.
    """
    print(f"--- [Orchestrator] 2단계: 증거 수집 시작 ---")
    
    # 웹 증거 수집과 파일 증거 수집 작업을 동시에 실행할 준비
    tasks = {
        "web": _get_web_evidence(report, topic),
        "files": _get_file_evidence(files, topic)
    }

    # asyncio.gather를 사용하여 모든 작업을 병렬로 실행하고 결과를 기다림
    results = await asyncio.gather(*tasks.values())
    
    evidence_map = dict(zip(tasks.keys(), results))

    print(f"--- [Orchestrator] 2단계: 증거 수집 완료 ---")

    return CoreEvidenceBriefing(
        web_evidence=evidence_map["web"],
        file_evidence=evidence_map["files"]
    )

async def _get_web_evidence(report: IssueAnalysisReport, topic: str) -> List[EvidenceItem]:
    """웹 검색을 수행하고 결과를 요약하여 증거 항목 리스트를 반환합니다."""
    # 검색 쿼리를 주제와 핵심 키워드를 조합하여 생성
    search_query = f"{topic}: {', '.join(report.core_keywords)}"
    search_results = await perform_web_search(search_query)
    
    if not search_results:
        return []

    # 각 검색 결과의 내용을 요약하는 작업을 병렬로 처리
    summary_tasks = [
        summarize_text(result["content"], topic)
        for result in search_results if result.get("content")
    ]
    summaries = await asyncio.gather(*summary_tasks)

    # 요약된 내용을 바탕으로 최종 증거 항목 생성
    evidence_items = [
        EvidenceItem(
            source=result.get("url", "Unknown Source"),
            summary=summaries[i]
        )
        for i, result in enumerate(search_results) if result.get("content")
    ]
            
    return evidence_items

async def _get_file_evidence(files: List[UploadFile], topic: str) -> List[EvidenceItem]:
    """업로드된 파일들을 처리하고 요약하여 증거 항목 리스트를 반환합니다."""
    if not files:
        return []

    # 각 파일을 읽고 텍스트를 추출하는 작업을 병렬로 처리
    processing_tasks = [process_uploaded_file(file) for file in files]
    file_contents = await asyncio.gather(*processing_tasks, return_exceptions=True)

    # 파일 내용 요약 작업을 병렬로 처리
    summary_tasks = [
        summarize_text(content, topic)
        for content in file_contents if isinstance(content, str)
    ]
    summaries = await asyncio.gather(*summary_tasks)

    # 요약된 내용을 바탕으로 최종 증거 항목 생성
    evidence_items = [
        EvidenceItem(
            source=files[i].filename,
            summary=summaries[i]
        )
        for i, content in enumerate(file_contents) if isinstance(content, str)
    ]
        
    return evidence_items

# --- [신규] 배심원단 선정 로직 ---

def _load_available_agents() -> List[Dict[str, str]]:
    """
    선택 가능한 에이전트 풀을 설정 파일에서 로드합니다.
    '사회자'과 같은 특수 역할은 이 풀에서 제외됩니다.
    """
    try:
        with open("src/app/core/settings/agents.json", "r", encoding="utf-8") as f:
            all_agents = json.load(f).get("agents", [])
            # '사회자'은 선택 대상이 아니므로 풀에서 제외
            return [agent for agent in all_agents if agent.get("name") != JUDGE_AGENT_NAME]
    except FileNotFoundError:
        raise ValueError("에이전트 설정 파일(agents.json)을 찾을 수 없습니다.")

async def select_debate_team(report: IssueAnalysisReport) -> DebateTeam:
    """
    분석 보고서를 기반으로 AI 배심원단을 선정하고 사회자을 지정합니다.
    """
    print(f"--- [Orchestrator] 3단계: 배심원단 선정 시작 ---")
    
    available_agents = _load_available_agents()
    if not available_agents:
        raise ValueError("사용 가능한 에이전트 풀이 비어있습니다. 설정을 확인하세요.")
    
    available_agent_names = [agent["name"] for agent in available_agents]

    # 팀 구성은 복잡한 추론이 필요하므로 고성능 모델 사용
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0.3, google_api_key=settings.GOOGLE_API_KEY)
    structured_llm = llm.with_structured_output(SelectedJury)

    system_prompt = f"""
    You are a master moderator assembling a panel of AI experts for a debate. Your task is to select a jury of 5 to 7 experts from the `Available Expert Agents Pool` ONLY. Do not invent names or select agents not on the list.

    **Debate Context (Issue Analysis Report):**
    {report.model_dump_json(indent=2)}

    **Available Expert Agents Pool:**
    - {', '.join(available_agent_names)}

    Based on the debate context, select the most relevant experts to form a diverse and effective jury. Ensure your selection covers the key issues and anticipated perspectives. Provide a concise reason for your team composition.
    You must only respond with a single, valid JSON object. Do NOT select a "Judge" or "Moderator"; that role is assigned separately.
    """

    prompt = ChatPromptTemplate.from_messages([("system", system_prompt)])
    chain = prompt | structured_llm

    # LLM을 통해 배심원단 초안 선택
    selected_jury = await chain.ainvoke({})
    
    # --- 규칙 강제 적용 ---
    # 1. LLM이 생성한 이름 중 실제 풀에 있는 이름만 필터링 (환각 방지)
    validated_jury_names = [name for name in selected_jury.agent_names if name in available_agent_names]
    
    # 2. '비판적 관점' 에이전트가 포함되었는지 확인 후 없으면 추가
    if CRITICAL_AGENT_NAME not in validated_jury_names:
        print(f"--- [규칙 적용] '{CRITICAL_AGENT_NAME}'이 누락되어 강제로 추가합니다. ---")
        validated_jury_names.append(CRITICAL_AGENT_NAME)
    
    # 3. 중복 제거 및 최종 배심원단 확정
    final_jury = list(dict.fromkeys(validated_jury_names))

    # 4. 최종 팀 구성 객체 생성
    final_team = DebateTeam(
        judge=JUDGE_AGENT_NAME, # 사회자은 규칙에 따라 별도 지정
        jury=final_jury,
        reason=selected_jury.reason
    )
    
    print(f"--- [Orchestrator] 3단계: 배심원단 선정 완료 ---")
    print(f"사회자: {final_team.judge}")
    print(f"배심원단: {final_team.jury}")
