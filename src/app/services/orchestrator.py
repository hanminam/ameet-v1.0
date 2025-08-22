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
JUDGE_AGENT_NAME = "재판관"
CRITICAL_AGENT_NAME = "비판적 관점"
TOPIC_ANALYST_NAME = "Topic Analyst"
JURY_SELECTOR_NAME = "Jury Selector"

# --- 설정 로더 ---
def _load_agent_configs(file_path: str) -> Dict[str, Dict]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            agents = json.load(f).get("agents", [])
            return {agent["name"]: agent for agent in agents}
    except FileNotFoundError:
        raise ValueError(f"에이전트 설정 파일({file_path})을 찾을 수 없습니다.")

# --- 1단계: 사건 분석 ---
async def analyze_topic(topic: str, special_agents: Dict[str, Dict]) -> IssueAnalysisReport:
    print(f"--- [Orchestrator] 1단계: 사건 분석 시작 (주제: {topic}) ---")
    
    analyst_config = special_agents.get(TOPIC_ANALYST_NAME)
    if not analyst_config:
        raise ValueError(f"'{TOPIC_ANALYST_NAME}' 설정을 찾을 수 없습니다.")

    llm = ChatGoogleGenerativeAI(
        model=analyst_config["model"],
        temperature=analyst_config["temperature"]
    )
    structured_llm = llm.with_structured_output(IssueAnalysisReport)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", analyst_config["prompt"]),
        ("human", "Please analyze the following topic: {topic}"),
    ])
    
    chain = prompt | structured_llm
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

async def select_debate_team(report: IssueAnalysisReport, jury_pool: Dict, special_agents: Dict) -> DebateTeam:
    """
    분석 보고서를 기반으로 AI 배심원단을 선정하고 재판관을 지정합니다.
    """
    print(f"--- [Orchestrator] 3단계: 배심원단 선정 시작 ---")
    
    selector_config = special_agents.get(JURY_SELECTOR_NAME)
    if not selector_config:
        raise ValueError(f"'{JURY_SELECTOR_NAME}' 설정을 찾을 수 없습니다.")

    # --- [핵심 수정] 1. LLM에게 전달할 에이전트 설명을 생성합니다. ---
    # 각 에이전트의 이름과 프롬프트의 첫 문장을 조합하여 역할 요약을 만듭니다.
    agent_pool_description_list = [
        f"- {name}: {config['prompt'].split('.')[0]}." 
        for name, config in jury_pool.items()
    ]
    agent_pool_description = "\n".join(agent_pool_description_list)

    llm = ChatGoogleGenerativeAI(
        model=selector_config["model"],
        temperature=selector_config["temperature"]
    )
    structured_llm = llm.with_structured_output(SelectedJury)

    # --- [핵심 수정] 2. 시스템 프롬프트에서 단순 이름 목록 대신, 역할 설명이 포함된 목록을 사용합니다. ---
    system_prompt = f"""
    You are a master moderator assembling a panel of AI experts for a debate. Your task is to select a jury of 5 to 7 experts from the `Available Expert Agents Pool` ONLY. [cite: 289]
    Do not invent names or select agents not on the list. [cite: 290]
    **Available Expert Agents Pool (Name: Role Summary):**
    {agent_pool_description}

    Based on the debate context provided by the user, select the most relevant experts to form a diverse and effective jury. Ensure your selection covers the key issues and anticipated perspectives. Provide a concise reason for your team composition in Korean. [cite: 292]
    You must only respond with a single, valid JSON object. Do NOT select a "Judge" or "Moderator"; that role is assigned separately. [cite: 293, 294]
    """
    # --- 수정 끝 ---

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Here is the debate context (Issue Analysis Report):\n\n{report_json}")
    ])
    
    chain = prompt | structured_llm
    selected_jury = await chain.ainvoke({
        "report_json": report.model_dump_json(indent=2)
    })
    
    # --- 규칙 강제 적용 로직 (이하 동일) ---
    available_agent_names = list(jury_pool.keys())
    validated_names = [name for name in selected_jury.agent_names if name in available_agent_names]
    
    if CRITICAL_AGENT_NAME not in validated_names:
        print(f"--- [규칙 적용] '{CRITICAL_AGENT_NAME}'이 누락되어 강제로 추가합니다. ---")
        validated_names.append(CRITICAL_AGENT_NAME)
    
    final_jury_names = list(dict.fromkeys(validated_names))

    final_jury_details = []
    for name in final_jury_names:
        agent_config = jury_pool.get(name)
        if agent_config:
            final_jury_details.append(AgentDetail(**agent_config))
    
    judge_config = special_agents.get(JUDGE_AGENT_NAME)
    if not judge_config:
        raise ValueError(f"'{JUDGE_AGENT_NAME}'의 설정을 찾을 수 없습니다.")

    final_team = DebateTeam(
        judge=AgentDetail(**judge_config),
        jury=final_jury_details,
        reason=selected_jury.reason
    )
    
    print(f"--- [Orchestrator] 3단계: 배심원단 선정 완료 ---")
    return final_team
