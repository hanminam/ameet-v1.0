import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

# 프로젝트의 루트 경로를 시스템 경로에 추가
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.app.models.discussion import AgentSettings

async def main():
    """
    MongoDB 'agents' 컬렉션에서 'discussion_participation_count' 필드가 없는
    모든 문서에 해당 필드를 생성하고 기본값 0을 설정합니다.
    """
    print("--- [Migration] 'discussion_participation_count' 필드 추가 스크립트를 시작합니다. ---")

    # 1. .env 파일에서 환경 변수 로드
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / '.env')
    mongo_url = os.getenv("MONGO_DB_URL")
    if not mongo_url:
        print("❌ [오류] .env 파일에 MONGO_DB_URL이 설정되지 않았습니다.")
        return

    # 2. 데이터베이스 연결 및 Beanie 초기화
    client = AsyncIOMotorClient(mongo_url)
    db_name = mongo_url.split("/")[-1].split("?")[0]
    await init_beanie(database=client[db_name], document_models=[AgentSettings])
    print(f"✅ MongoDB '{db_name}' 데이터베이스에 연결되었습니다.")

    # 3. PyMongo를 사용하여 직접 업데이트
    collection = AgentSettings.get_motor_collection()
    result = await collection.update_many(
        {"discussion_participation_count": {"$exists": False}},
        {"$set": {"discussion_participation_count": 0}}
    )

    print("\n--- [Migration] 작업 완료 ---")
    print(f"✅ 총 {result.modified_count}개의 에이전트에 'discussion_participation_count: 0' 필드를 추가했습니다.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())