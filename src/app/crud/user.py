import json
from typing import List, Optional
from pathlib import Path
import asyncio

# aiofiles 라이브러리를 사용하여 비동기 파일 처리를 합니다.
# requirements.txt에 aiofiles가 이미 포함되어 있어 별도 설치가 필요 없습니다.
import aiofiles
from datetime import datetime

from app.models.user import User
from app.schemas.user import UserCreate
from app.core.security import get_password_hash

# 데이터 파일 경로 설정
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"

# --- 비동기 파일 I/O 헬퍼 함수 ---
async def _read_users_from_file() -> List[dict]:
    """aiofiles를 사용하여 비동기적으로 JSON 파일에서 사용자 목록을 읽습니다."""
    if not USERS_FILE.is_file():
        return []
    try:
        async with aiofiles.open(USERS_FILE, mode='r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

async def _write_users_to_file(users: List[dict]):
    """aiofiles를 사용하여 비동기적으로 사용자 목록을 JSON 파일에 씁니다."""
    # 데이터 디렉토리가 없으면 생성
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(USERS_FILE, mode='w', encoding='utf-8') as f:
        # JSON 직렬화는 동기 작업이지만 매우 빠르므로 그대로 사용합니다.
        content = json.dumps(users, indent=4, ensure_ascii=False)
        await f.write(content)

# --- CRUD 함수 ---

async def get_user_by_email(email: str) -> Optional[User]:
    """이메일로 사용자를 조회합니다."""
    users = await _read_users_from_file()
    for user_data in users:
        if user_data["email"] == email:
            return User(**user_data)
    return None

async def get_users(skip: int = 0, limit: int = 100) -> List[User]:
    """사용자 목록을 페이지네이션하여 조회합니다."""
    users = await _read_users_from_file()
    paginated_users = users[skip : skip + limit]
    return [User(**user_data) for user_data in paginated_users]

async def create_user(user: UserCreate) -> User:
    """새로운 사용자를 생성하고, 가입일과 마지막 접속일을 기록합니다."""
    users = await _read_users_from_file()
    
    if any(u["email"] == user.email for u in users):
        raise ValueError("Email already registered")

    hashed_password = get_password_hash(user.password)
    new_user_id = max([u.get("id", 0) for u in users] or [0]) + 1
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    new_user_data = {
        "id": new_user_id,
        "name": user.name,
        "email": user.email,
        "hashed_password": hashed_password,
        "role": user.role,
        "created_at": current_time,
        "last_login_at": current_time
    }
    
    users.append(new_user_data)
    await _write_users_to_file(users)
    
    return User(**new_user_data)

async def delete_user(user_id: int) -> Optional[User]:
    """ID로 사용자를 삭제합니다."""
    users = await _read_users_from_file()
    user_to_delete = None
    updated_users = [u for u in users if u.get("id") != user_id]

    if len(users) != len(updated_users):
        user_to_delete_data = next((u for u in users if u.get("id") == user_id), None)
        if user_to_delete_data:
            user_to_delete = User(**user_to_delete_data)
        await _write_users_to_file(updated_users)
        
    return user_to_delete

# --- 마지막 로그인 시간 업데이트 함수 ---
async def update_user_last_login(email: str) -> Optional[User]:
    """사용자의 마지막 로그인 시간을 현재 시간으로 업데이트합니다."""
    users = await _read_users_from_file()
    user_found = False
    updated_user_data = None
    for user_data in users:
        if user_data["email"] == email:
            user_data["last_login_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            updated_user_data = user_data
            user_found = True
            break
    
    if user_found:
        await _write_users_to_file(users)
        return User(**updated_user_data)
    return None

# --- 역할 기반 사용자 조회 함수 ---
async def get_users_by_role(role: str) -> List[User]:
    """특정 역할을 가진 사용자 목록을 가입일 최신순으로 정렬하여 반환합니다."""
    users = await _read_users_from_file()
    
    role_users = [u for u in users if u.get("role") == role]
    
    # 가입일(created_at) 기준으로 내림차순 정렬 (최신 가입자 순)
    sorted_users = sorted(
        role_users, 
        key=lambda u: u.get("created_at", "1970-01-01 00:00:00"), 
        reverse=True
    )
    
    return [User(**user_data) for user_data in sorted_users]