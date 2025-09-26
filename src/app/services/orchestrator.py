# src/app/services/orchestrator.py

import asyncio
import json
from typing import List, Dict, Tuple
from fastapi import UploadFile

from beanie.operators import In
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings, logger
from app.models.discussion import AgentSettings, AgentConfig, SystemSettings

from app.schemas.orchestration import (
    IssueAnalysisReport, 
    CoreEvidenceBriefing, 
    EvidenceItem,
    SelectedJury,
    DebateTeam,
    AgentDetail
)

from app.tools.search import perform_web_search_async
from app.services.document_processor import process_uploaded_file
from app.services.summarizer import summarize_text
from app import db

# --- 역할 기반 상수 정의 ---
JUDGE_AGENT_NAME = "재판관"
CRITICAL_AGENT_NAME = "비판적 관점"
TOPIC_ANALYST_NAME = "Topic Analyst"
JURY_SELECTOR_NAME = "Jury Selector"

# --- 아이콘 생성을 위한 헬퍼 함수 및 상수 ---
ICON_MAP = {
    # 역할/직업
    "재판관": "🧑", "분석가": "📊", "경제": "🌍", "산업": "🏭", "재무": "💹",
    "트렌드": "📈", "비판": "🤔", "전문가": "🧑", "미시": "🛒", "미래학자": "🔭",
    "물리학": "⚛️", "양자": "🌀", "의학": "⚕️", "심리학": "🧠", "뇌과학": "⚡️",
    "문학": "✍️", "역사": "🏛️", "생물학": "🧬", "법의학": "🔬", "법률": "⚖️",
    "회계": "🧾", "인사": "👥", "인류학": "🗿", "IT": "💻", "개발": "👨‍💻",
    # 고유명사/인물
    "버핏": "👴", "린치": "👨‍💼", "잡스": "💡", "머스크": "🚀", "베이조스": "📦",
    "웰치": "🏆", "아인슈타인": "🌌",
    # 기타 키워드
    "선정": "📋", "분석": "🔎"
}
DEFAULT_ICON = "🧑"

def _get_icon_for_agent(agent_data: dict) -> str:
    """
    에이전트의 이름과 프롬프트를 기반으로 가장 적합한 아이콘 '하나'를 반환합니다.
    일치하는 키워드가 여러 개일 경우, 가장 긴 키워드를 우선합니다.
    """
    name = agent_data.get("name", "")
    prompt = agent_data.get("prompt", "")

    # 1순위: 이름에서 가장 길게 일치하는 키워드 찾기
    name_matches = [keyword for keyword in ICON_MAP if keyword in name]
    if name_matches:
        best_match = max(name_matches, key=len)
        return ICON_MAP[best_match]

    # 2순위: 프롬프트에서 가장 길게 일치하는 키워드 찾기
    prompt_matches = [keyword for keyword in ICON_MAP if keyword in prompt]
    if prompt_matches:
        best_match = max(prompt_matches, key=len)
        return ICON_MAP[best_match]

    # 3순위: 기본 아이콘 반환
    return DEFAULT_ICON

# --- DB에서 Active 상태의 에이전트를 조회하는 함수 ---
async def get_active_agents_from_db() -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    """
    DB에서 'active' 상태인 에이전트들을 조회하여 'special'과 'expert' 타입으로 분리하여 반환합니다.
    반환되는 딕셔너리의 값(value)에 'name' 필드를 포함시킵니다.
    """
    special_agents = {}
    expert_agents = {}
    
    active_agents_cursor = AgentSettings.find(AgentSettings.status == "active")
    
    async for agent in active_agents_cursor:
        # config 딕셔너리와 name을 합쳐서 완전한 에이전트 정보 딕셔너리를 생성
        full_agent_details = {
            "name": agent.name,
            **agent.config.model_dump()
        }
        
        if agent.agent_type == "special":
            special_agents[agent.name] = full_agent_details
        else: # "expert"
            expert_agents[agent.name] = full_agent_details
            
    return special_agents, expert_agents

# --- 1단계: 사건 분석 ---
async def analyze_topic(topic: str, special_agents: Dict[str, Dict], discussion_id: str) -> IssueAnalysisReport:
    print(f"--- [Orchestrator] 1단계: 사건 분석 시작 (ID: {discussion_id}) ---")
    
    analyst_config = special_agents.get(TOPIC_ANALYST_NAME)
    if not analyst_config:
        raise ValueError(f"'{TOPIC_ANALYST_NAME}' 설정을 찾을 수 없습니다.")

    llm = ChatGoogleGenerativeAI(
        model=analyst_config["model"],
        temperature=analyst_config["temperature"],
        location="asia-northeast3"
    )
    structured_llm = llm.with_structured_output(IssueAnalysisReport)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", analyst_config["prompt"]),
        ("human", "Please analyze the following topic: {topic}"),
    ])
    
    chain = prompt | structured_llm
    
    # LLM 호출 시 config에 태그 추가
    report = await chain.ainvoke(
        {"topic": topic},
        config={"tags": [f"discussion_id:{discussion_id}"]}
    )
    
    print(f"--- [Orchestrator] 1단계: 사건 분석 완료 ---")
    return report

# --- 증거 수집 로직 ---
async def gather_evidence(
    report: IssueAnalysisReport, 
    files: List[UploadFile],
    topic: str,
    discussion_id: str
) -> CoreEvidenceBriefing:
    """
    분석 보고서와 사용자 파일을 기반으로 '핵심 자료집'을 생성합니다.
    웹 검색과 파일 처리를 병렬로 수행하여 효율성을 높입니다.
    """
    print(f"--- [Orchestrator] 2단계: 증거 수집 시작 (ID: {discussion_id}) ---")
    tasks = {
        "web": _get_web_evidence(report, topic, discussion_id),
        "files": _get_file_evidence(files, topic, discussion_id)
    }

    # asyncio.gather를 사용하여 모든 작업을 병렬로 실행하고 결과를 기다림
    results = await asyncio.gather(*tasks.values())
    
    evidence_map = dict(zip(tasks.keys(), results))

    print(f"--- [Orchestrator] 2단계: 증거 수집 완료 ---")

    return CoreEvidenceBriefing(
        web_evidence=evidence_map["web"],
        file_evidence=evidence_map["files"]
    )

async def _get_web_evidence(report: IssueAnalysisReport, topic: str, discussion_id: str) -> List[EvidenceItem]:
    search_query = f"{topic}: {', '.join(report.core_keywords)}"
    search_results = await perform_web_search_async(search_query) # 웹 검색 자체는 LLM 호출이 아님
    
    if not search_results:
        return []

    summary_tasks = [
        # summarize_text 호출 시 discussion_id 전달
        summarize_text(result["content"], topic, discussion_id)
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

async def _get_file_evidence(files: List[UploadFile], topic: str, discussion_id: str) -> List[EvidenceItem]:
    """업로드된 파일들을 처리하고 요약하여 증거 항목 리스트를 반환합니다."""
    if not files:
        return []

    # 각 파일을 읽고 텍스트를 추출하는 작업을 병렬로 처리
    processing_tasks = [process_uploaded_file(file) for file in files]
    file_contents = await asyncio.gather(*processing_tasks, return_exceptions=True)

    # 파일 내용 요약 작업을 병렬로 처리
    summary_tasks = [
        # summarize_text 호출 시 discussion_id 전달
        summarize_text(content, topic, discussion_id)
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

async def select_debate_team(report: IssueAnalysisReport, jury_pool: Dict, special_agents: Dict, discussion_id: str) -> DebateTeam:
    """
    분석 보고서를 기반으로 AI 배심원단을 선정하고, 필요 시 새로운 에이전트를 생성한 후 재판관을 지정합니다.
    """
    print(f"--- [Orchestrator] 3단계: 배심원단 선정 시작 (ID: {discussion_id}) ---")

    selector_config = special_agents.get(JURY_SELECTOR_NAME)
    if not selector_config:
        raise ValueError(f"'{JURY_SELECTOR_NAME}' 설정을 찾을 수 없습니다.")

    agent_pool_description_list = [
        f"- {name}: {config['prompt'].split('.')[0]}."
        for name, config in jury_pool.items()
    ]
    agent_pool_description = "\n".join(agent_pool_description_list)

    system_prompt = f"""
    You are a master moderator and an expert talent scout assembling a panel of AI experts for a debate. Your primary goal is to create the most insightful and diverse debate panel possible for the given topic.

    **Your Tasks:**
    1.  **Select from Existing Experts:** From the `Available Expert Agents Pool`, select the 4 to 6 most relevant experts.
    2.  **Propose New Experts:** Critically evaluate your selection. If you believe a crucial perspective is missing, propose 1 to 2 new, highly specific expert roles that do not exist in the current pool. The proposed role names must be in KOREAN. **The names should be concise and simple, without any parentheses or repeated phrases (e.g., use '여론조사 전문가', not '여론조사 전문가(여론조사 전문가)').**
    3.  **Provide Justification:** Write a concise reason explaining your selections and any new proposals, detailing why this specific combination of experts is optimal for the given debate topic. The justification must be written in KOREAN.

    **Available Expert Agents Pool (Name: Role Summary):**
    {agent_pool_description}

    You must only respond with a single, valid JSON object that strictly adheres to the required schema.
    """

    llm = ChatGoogleGenerativeAI(
        model=selector_config["model"],
        temperature=selector_config["temperature"]
    )
    structured_llm = llm.with_structured_output(SelectedJury)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Here is the debate context (Issue Analysis Report):\n\n{report_json}")
    ])

    chain = prompt | structured_llm
    selected_jury: SelectedJury = await chain.ainvoke(
        {"report_json": report.model_dump_json(indent=2)},
        config={"tags": [f"discussion_id:{discussion_id}", f"agent_name:{JURY_SELECTOR_NAME}"]}
    )

    # 하드코딩된 프롬프트 대신 DB에서 기본 프롬프트를 조회합니다.
    db_name = settings.MONGO_DB_URL.split("/")[-1].split("?")[0]
    settings_collection = db.mongo_client[db_name]["system_settings"]
    default_prompt_setting = await settings_collection.find_one({"key": "default_agent_prompt"})
    
    PROMPT_TEMPLATE = (
        "당신의 역할은 '{role}'이며 지정된 역할 관점에서 말하세요.\n"
        "당신의 역할에 맞는 대화스타일을 사용하세요.\n"
        "토의 규칙을 숙지하고 토론의 목표를 달성하기 위해 제시된 의견들을 바탕으로 보완의견을 제시하거나, 주장을 강화,철회,수정 하세요.\n"
        "모든 의견은 논리적이고 일관성이 있어야 하며 신뢰할 수 있는 출처에 기반해야하고 자세하게 답변하여야 합니다.\n"
        "사용자가 질문한 언어로 답변하여야 합니다."
    )
    
    if default_prompt_setting and default_prompt_setting.get("value"):
        PROMPT_TEMPLATE = default_prompt_setting["value"]
        logger.info("--- [Orchestrator] DB에서 기본 프롬프트를 성공적으로 로드했습니다. ---")
    else:
        logger.info("--- [Orchestrator] DB에 기본 프롬프트 설정이 없어 기본값으로 생성합니다. ---")
        # Beanie 대신 motor 드라이버를 사용하여 DB에 저장
        await settings_collection.update_one(
            {"key": "default_agent_prompt"},
            {"$set": {
                "value": PROMPT_TEMPLATE,
                "description": "Jury Selector가 동적으로 에이전트를 생성할 때 사용하는 기본 프롬프트 템플릿. '{role}' 변수를 포함해야 합니다."
            }},
            upsert=True
        )

    newly_created_agents = []
    if selected_jury.new_agent_proposals:
        for agent_name in selected_jury.new_agent_proposals:
            existing_agent = await AgentSettings.find_one(AgentSettings.name == agent_name)
            if not existing_agent:
                agent_prompt = PROMPT_TEMPLATE.format(role=agent_name)

                agent_info_for_icon = {"name": agent_name, "prompt": agent_prompt}
                selected_icon = _get_icon_for_agent(agent_info_for_icon)

                # 신규 에이전트 설정에서 'tools' 필드 완전 삭제
                new_agent_config = AgentConfig(
                    prompt=agent_prompt,
                    model="gemini-1.5-pro",
                    temperature=0.3,
                    icon=selected_icon
                )

                new_agent = AgentSettings(
                    name=agent_name,
                    agent_type="expert",
                    version=1,
                    status="active",
                    config=new_agent_config,
                    last_modified_by="Jury_Selector_AI",
                    discussion_participation_count=0
                )
                await new_agent.insert()
                print(f"--- [Orchestrator] 신규 에이전트 생성 및 DB 저장 완료: {agent_name} (Icon: {selected_icon}) ---")

                newly_created_agents.append(AgentDetail(**{"name": agent_name, **new_agent_config.model_dump()}))

    final_jury_details = [AgentDetail(**jury_pool[name]) for name in selected_jury.selected_agents if name in jury_pool]
    final_jury_details.extend(newly_created_agents)

    if CRITICAL_AGENT_NAME in jury_pool and not any(agent.name == CRITICAL_AGENT_NAME for agent in final_jury_details):
        print(f"--- [규칙 적용] '{CRITICAL_AGENT_NAME}'이 누락되어 강제로 추가합니다. ---")
        final_jury_details.append(AgentDetail(**jury_pool[CRITICAL_AGENT_NAME]))

    final_jury_names = [agent.name for agent in final_jury_details]
    if final_jury_names:
        await AgentSettings.find_many(
            In(AgentSettings.name, final_jury_names)
        ).update({"$inc": {AgentSettings.discussion_participation_count: 1}})
        print(f"--- [Orchestrator] 참여 에이전트 카운트 업데이트 완료: {final_jury_names} ---")

    judge_config = special_agents.get(JUDGE_AGENT_NAME)
    if not judge_config:
        raise ValueError(f"'{JUDGE_AGENT_NAME}'의 설정을 찾을 수 없습니다.")

    final_team = DebateTeam(
        discussion_id=discussion_id,
        judge=AgentDetail(**judge_config),
        jury=final_jury_details,
        reason=selected_jury.reason
    )

    print(f"--- [Orchestrator] 3단계: 배심원단 선정 완료 ---")
    return final_team