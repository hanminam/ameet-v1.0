# scripts/migrate_users_to_mongo.py

import asyncio
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

# 프로젝트 루트 경로 추가
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.app.models.discussion import User

async def main():
    print("--- [Migration] users.json 데이터를 MongoDB로 이전 시작 ---")

    # 1. .env 파일 로드 및 DB 연결
    load_dotenv()
    mongo_url = "mongodb+srv://root:Kimnc0624!%40@cluster0.6ckqorp.mongodb.net/ameet_db?retryWrites=true&w=majority"
    if not mongo_url:
        print("❌ [오류] .env 파일에 MONGO_DB_URL이 없습니다.")
        return

    client = AsyncIOMotorClient(mongo_url)
    db_name = mongo_url.split("/")[-1].split("?")[0]
    await init_beanie(database=client[db_name], document_models=[User])
    print(f"✅ MongoDB '{db_name}' 데이터베이스에 연결되었습니다.")

    # 2. 기존 users.json 파일 읽기
    json_path = Path(__file__).resolve().parent.parent / "src" / "app" / "data" / "users.json"
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            users_from_json = json.load(f)
    except FileNotFoundError:
        print(f"❌ [오류] '{json_path}' 파일을 찾을 수 없습니다.")
        return

    # 3. MongoDB에 데이터 삽입 (이메일 중복 체크)
    inserted_count = 0
    for user_data in users_from_json:
        existing_user = await User.find_one(User.email == user_data["email"])
        if existing_user:
            print(f"🟡 [SKIP] '{user_data['email']}' 사용자는 이미 DB에 존재합니다.")
            continue

        # last_login_at 필드가 없을 경우 created_at 값으로 설정
        if 'last_login_at' not in user_data:
            user_data['last_login_at'] = user_data.get('created_at')

        new_user = User(
            name=user_data["name"],
            email=user_data["email"],
            hashed_password=user_data["hashed_password"],
            role=user_data["role"],
            # created_at, last_login_at은 Beanie 모델의 기본값으로 자동 생성되므로
            # json 파일에 해당 필드가 없어도 괜찮습니다.
        )
        await new_user.insert()
        inserted_count += 1
        print(f"➕ [INSERT] '{user_data['email']}' 사용자 정보를 DB에 추가했습니다.")

    print("\n--- [Migration] 작업 완료 ---")
    print(f"✅ 총 {inserted_count}명의 신규 사용자를 MongoDB에 추가했습니다.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())