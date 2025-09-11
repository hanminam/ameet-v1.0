import json
from pathlib import Path

# src 폴더가 현재 경로에 있다고 가정하고 security 모듈을 가져옵니다.
# 이 스크립트는 반드시 프로젝트 최상위 폴더에서 실행해야 합니다.
try:
    from src.app.core.security import get_password_hash
except ImportError:
    print("오류: 이 스크립트는 프로젝트의 최상위 폴더에서 실행해야 합니다.")
    print("      'src' 폴더를 찾을 수 없습니다.")
    exit(1)

# 생성할 사용자 정보 (비밀번호는 일반 텍스트)
users_to_create = [
    {
        "id": 1,
        "name": "Admin User",
        "email": "admin@example.com",
        "password": "adminpassword", # <-- 해시될 일반 비밀번호
        "role": "admin"
    },
    {
        "id": 2,
        "name": "Normal User",
        "email": "user@example.com",
        "password": "userpassword", # <-- 해시될 일반 비밀번호
        "role": "user"
    }
]

# users.json 파일이 생성될 최종 경로
output_dir = Path(__file__).parent / "src" / "app" / "data"
output_file = output_dir / "users.json"

def create_users_file():
    """사용자 목록을 기반으로 암호화된 users.json 파일을 생성합니다."""
    
    print("`users.json` 파일 생성을 시작합니다...")
    
    processed_users = []
    for user in users_to_create:
        print(f"  - '{user['email']}' 사용자의 비밀번호를 해시하는 중...")
        # 'password' 키를 'hashed_password'로 바꾸고 값을 해시 값으로 교체
        hashed_password = get_password_hash(user.pop("password"))
        user["hashed_password"] = hashed_password
        processed_users.append(user)
    
    # 데이터 폴더가 없으면 생성
    print(f"\n데이터 폴더를 확인/생성합니다: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 최종 데이터를 JSON 파일로 저장
    print(f"파일을 저장합니다: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(processed_users, f, ensure_ascii=False, indent=4)
        
    print("\n✅ 성공! `users.json` 파일이 성공적으로 생성되었습니다.")
    print("이제 이 상태로 Cloud Run에 다시 배포하세요.")

if __name__ == "__main__":
    create_users_file()