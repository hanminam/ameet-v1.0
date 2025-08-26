import asyncio
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

# --- 프로젝트 경로 설정 ---
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.app.models.discussion import AgentSettings, AgentConfig

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

    # 2. 데이터베이스 연결 및 Beanie 초기화
    client = AsyncIOMotorClient(mongo_url)
    db_name = mongo_url.split("/")[-1].split("?")[0]
    await init_beanie(database=client[db_name], document_models=[AgentSettings])
    print(f"✅ [Migration v2] MongoDB '{db_name}' 데이터베이스에 연결되었습니다.")

    # --- [신규] 기존 데이터 삭제 ---
    print("🗑️ [Migration v2] 기존 'agents' 컬렉션의 모든 데이터를 삭제합니다...")
    await AgentSettings.delete_all()
    print("✅ [Migration v2] 데이터 삭제 완료.")
    # ---

    # 3. JSON 파일 경로 설정 및 데이터 로드
    base_path = Path(__file__).resolve().parent.parent
    
    # [수정] 파일별로 agent_type을 지정하여 로드
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
                    agent_data["agent_type"] = agent_type # agent_type 정보 주입
                all_agents_to_insert.extend(data)
            print(f"📄 [Migration v2] '{file_path.name}' 파일에서 '{agent_type}' 타입 에이전트 정보를 로드했습니다.")
        except FileNotFoundError:
            print(f"⚠️ [경고] '{file_path.name}' 파일을 찾을 수 없습니다. 건너뜁니다.")

    # 4. MongoDB에 데이터 삽입
    inserted_count = 0
    for agent_data in all_agents_to_insert:
        agent_name = agent_data.get("name")
        agent_type = agent_data.get("agent_type") # 주입된 agent_type 사용
        if not agent_name:
            continue

        agent_config = AgentConfig(
            prompt=agent_data.get("prompt", ""),
            model=agent_data.get("model", "gemini-1.5-pro"),
            temperature=agent_data.get("temperature", 0.2),
            tools=agent_data.get("tools", []),
            # icon 필드는 선택 사항이므로 없어도 무방
        )

        new_agent_doc = AgentSettings(
            name=agent_name,
            agent_type=agent_type, # [수정] agent_type 필드 추가
            version=1,
            status="active",
            config=agent_config,
            last_modified_by="system_migration_v2"
        )

        await new_agent_doc.insert()
        inserted_count += 1
        print(f"➕ [Migration v2] '{agent_name}' ({agent_type}) 에이전트를 DB에 추가했습니다.")

    print("\n--- [Migration v2] 작업 완료 ---")
    print(f"총 {inserted_count}개의 에이전트를 새로 추가했습니다.")
    print("---------------------------------")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())