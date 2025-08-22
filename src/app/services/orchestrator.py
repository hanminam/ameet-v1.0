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
    DebateTeam,
    AgentDetail
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

# --- 증거 수집 로직 ---
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

# --- 배심원단 선정 로직 ---
def _load_available_agents() -> List[Dict[str, str]]:
    """
    선택 가능한 에이전트 풀을 설정 파일에서 로드합니다.
    '재판관'과 같은 특수 역할은 이 풀에서 제외됩니다.
    """
    try:
        # 이 경로는 src/app/core/settings/agents.json을 가리킵니다.
        # 해당 위치로 agents.json 파일을 이동시켜야 합니다.
        with open("app/core/settings/agents.json", "r", encoding="utf-8") as f:
            all_agents = json.load(f).get("agents", [])
            return [agent for agent in all_agents if agent.get("name") != JUDGE_AGENT_NAME]
    except FileNotFoundError:
        raise ValueError("에이전트 설정 파일(app/core/settings/agents.json)을 찾을 수 없습니다.")
    
def _load_agent_configs(file_path: str) -> Dict[str, Dict]:
    """설정 파일에서 에이전트 목록을 로드하여 이름-설정 맵을 반환합니다."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            agents = json.load(f).get("agents", [])
            return {agent["name"]: agent for agent in agents}
    except FileNotFoundError:
        raise ValueError(f"에이전트 설정 파일({file_path})을 찾을 수 없습니다.")

async def select_debate_team(report: IssueAnalysisReport) -> DebateTeam:
    """
    분석 보고서를 기반으로 AI 배심원단을 선정하고 재판관을 지정합니다.
    """
    print(f"--- [Orchestrator] 3단계: 배심원단 선정 시작 ---")
    
    jury_pool_configs = _load_agent_configs("app/core/settings/agents.json")
    special_agent_configs = _load_agent_configs("app/core/settings/special_agents.json")

    available_agent_names = list(jury_pool_configs.keys())

    llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0.3)
    structured_llm = llm.with_structured_output(SelectedJury)

    # --- [수정] 프롬프트에 한국어 이유 명시 ---
    system_prompt = f"""
    You are a master moderator...
    
    Available Expert Agents Pool:
    - {', '.join(available_agent_names)}

    ...Provide a concise reason for your team composition in Korean.
    You must only respond with a single, valid JSON object...
    """

    prompt = ChatPromptTemplate.from_messages([("system", system_prompt)])
    chain = prompt | structured_llm
    
    selected_jury = await chain.ainvoke({"report_json": report.model_dump_json(indent=2)})
    
    validated_jury_names = [name for name in selected_jury.agent_names if name in available_agent_names]
    
    if CRITICAL_AGENT_NAME not in validated_jury_names:
        validated_jury_names.append(CRITICAL_AGENT_NAME)
    
    final_jury_names = list(dict.fromkeys(validated_jury_names))

    # --- [수정] 이름 목록을 AgentDetail 객체 목록으로 변환 ---
    final_jury_details = [
        AgentDetail(name=name, model=jury_pool_configs.get(name, {}).get("model", "N/A"))
        for name in final_jury_names
    ]
    
    judge_config = special_agent_configs.get(JUDGE_AGENT_NAME)
    if not judge_config:
        raise ValueError(f"'{JUDGE_AGENT_NAME}'의 설정을 찾을 수 없습니다.")

    final_team = DebateTeam(
        judge=AgentDetail(name=JUDGE_AGENT_NAME, model=judge_config.get("model", "N/A")),
        jury=final_jury_details,
        reason=selected_jury.reason
    )
    
    print(f"--- [Orchestrator] 3단계: 배심원단 선정 완료 ---")
    print(f"재판관: {final_team.judge.name} ({final_team.judge.model})")
    print(f"배심원단: {[f'{agent.name} ({agent.model})' for agent in final_team.jury]}")

    return final_team
