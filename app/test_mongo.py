import os
from pymongo import MongoClient
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# Connection String 가져오기
MONGO_URI = os.getenv("MONGO_DB_URL")

print("--- [Debug] ---")
print(f"Loaded MONGO_DB_URL: {MONGO_URI}")
print("---------------")

# 만약 MONGO_URI가 없다면 스크립트를 중지하고 메시지를 출력합니다.
if not MONGO_URI:
    print("❌ 오류: .env 파일에서 MONGO_DB_URL을 찾을 수 없습니다. 파일 위치와 변수명을 다시 확인해주세요.")
    exit()
# --- [디버깅 코드 끝] ---

try:
    # MongoDB 클라이언트 생성
    client = MongoClient(MONGO_URI)

    # 서버 정보 가져오기 (연결 테스트)
    server_info = client.server_info()
    print("✅ MongoDB Atlas에 성공적으로 연결되었습니다!")
    print(f"Server Version: {server_info['version']}")

    # 데이터베이스 및 컬렉션 확인
    db = client.ameet_db
    collections = db.list_collection_names()
    print(f"\n'ameet_db' 데이터베이스의 컬렉션 목록: {collections}")

    # 테스트 데이터 삽입
    agents_collection = db.agents
    test_agent = {"name": "Test Agent", "model": "test-model"}
    result = agents_collection.insert_one(test_agent)
    print(f"\n📝 테스트 데이터 삽입 완료. (ID: {result.inserted_id})")

    # 삽입된 데이터 삭제
    agents_collection.delete_one({"_id": result.inserted_id})
    print("🗑️ 테스트 데이터 삭제 완료.")

except Exception as e:
    print(f"❌ 연결 실패: {e}")

finally:
    if 'client' in locals():
        client.close()