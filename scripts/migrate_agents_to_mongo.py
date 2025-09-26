import asyncio
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.app.models.discussion import AgentSettings, AgentConfig

# --- [신규] 에이전트 특성에 맞는 아이콘을 추천하기 위한 키워드 맵 ---
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

def get_icon_for_agent(agent_data: dict) -> str:
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

async def main():
    """
    JSON 파일의 에이전트 설정을 MongoDB로 마이그레이션합니다.
    [수정] agent_type 필드를 추가하고, 실행 시 기존 데이터를 모두 삭제한 후 새로 추가합니다.
    """
    print("--- [Migration v2] 스크립트를 시작합니다. ---")

    # 1. .env 파일에서 환경 변수 로드
    load_dotenv()
    mongo_url = os.getenv("MONGO_DB_URL")
    if not mongo_url:
        print("❌ [오류] .env 파일에 MONGO_DB_URL이 설정되지 않았습니다.")
        return

    client = AsyncIOMotorClient(mongo_url)
    db_name = mongo_url.split("/")[-1].split("?")[0]
    await init_beanie(database=client[db_name], document_models=[AgentSettings])
    print(f"✅ [Migration v4] MongoDB '{db_name}' 데이터베이스에 연결되었습니다.")

    print("🗑️ [Migration v4] 기존 'agents' 컬렉션의 모든 데이터를 삭제합니다...")
    await AgentSettings.delete_all()
    print("✅ [Migration v4] 데이터 삭제 완료.")

    # 3. JSON 파일 경로 설정 및 데이터 로드
    base_path = Path(__file__).resolve().parent.parent
    files_to_migrate = {
        "special": base_path / "src" / "app" / "core" / "settings" / "special_agents.json",
        "expert": base_path / "src" / "app" / "core" / "settings" / "agents.json"
    }
    all_agents_to_insert = []
    for agent_type, file_path in files_to_migrate.items():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f).get("agents", [])
                for agent_data in data:
                    agent_data["agent_type"] = agent_type
                all_agents_to_insert.extend(data)
        except FileNotFoundError:
            print(f"⚠️ [경고] '{file_path.name}' 파일을 찾을 수 없습니다.")

    # MongoDB에 데이터 삽입
    inserted_count = 0
    for agent_data in all_agents_to_insert:
        agent_name = agent_data.get("name")
        if not agent_name: continue

        # get_icon_for_agent 함수를 호출하여 아이콘 결정
        selected_icon = get_icon_for_agent(agent_data)

        agent_config = AgentConfig(
            prompt=agent_data.get("prompt", ""),
            model=agent_data.get("model", "gemini-2.5-flash"),
            temperature=agent_data.get("temperature", 0.2),
            tools=agent_data.get("tools", []),
            icon=selected_icon # 결정된 아이콘을 할당
        )

        new_agent_doc = AgentSettings(
            name=agent_name,
            agent_type=agent_data.get("agent_type"),
            version=1,
            status="active",
            config=agent_config,
            last_modified_by="system_migration_v4"
        )

        await new_agent_doc.insert()
        inserted_count += 1
        print(f"➕ [Migration v4] '{agent_name}' ({agent_data.get('agent_type')}) 에이전트에 아이콘 '{selected_icon}' 할당 완료.")

    print("\n--- [Migration v4] 작업 완료 ---")
    print(f"총 {inserted_count}개의 에이전트를 새로 추가했습니다.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())