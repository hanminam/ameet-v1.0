# test_sync_connection.py

import os
from dotenv import load_dotenv
import pymysql

# .env 파일에서 환경 변수 로드
load_dotenv()

# .env 파일에서 DB 접속 정보 가져오기
db_host = os.getenv("DB_HOST")
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")
db_name = os.getenv("DB_NAME")
db_port = int(os.getenv("DB_PORT", 3306))

print("--- [Sync Connection Test] ---")
print(f"Attempting to connect to {db_host}:{db_port} as {db_user}...")

try:
    # pymysql을 사용해 직접 연결 시도
    connection = pymysql.connect(
        host=db_host,
        user=db_user,
        password=db_password,
        database=db_name,
        port=db_port,
        connect_timeout=10
    )

    print("\n✅✅✅ 동기 방식(pymysql) 연결에 성공했습니다! ✅✅✅")
    print("네트워크나 방화벽에는 문제가 없습니다.")

    connection.close()
    print("\nConnection closed.")

except Exception as e:
    print(f"\n❌❌❌ 동기 방식 연결에 실패했습니다: {e} ❌❌❌")
    print("로컬 PC의 방화벽, 백신 프로그램, 또는 VPN 설정을 확인해보세요.")

print("----------------------------")