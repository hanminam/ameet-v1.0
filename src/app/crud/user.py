# src/app/crud/user.py

import json
from typing import List, Optional
from pathlib import Path
import asyncio

from app.models.user import User
from app.schemas.user import UserCreate
from app.core.security import get_password_hash, verify_password

# Define the path to the users.json file
# This assumes the script is run from the root of the project
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"

# --- Async File I/O Helpers ---
async def _read_users_from_file() -> List[dict]:
    """Asynchronously reads the users from the JSON file."""
    if not USERS_FILE.is_file():
        return []
    async with asyncio.to_thread(USERS_FILE.read_text, "utf-8") as f:
        content = await asyncio.to_thread(f.read)
        return json.loads(content)

async def _write_users_to_file(users: List[dict]):
    """Asynchronously writes the list of users to the JSON file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with asyncio.to_thread(USERS_FILE.write_text, "utf-8") as f:
        content = json.dumps(users, indent=4, ensure_ascii=False)
        await asyncio.to_thread(f.write, content)

# --- CRUD Functions ---

async def get_user_by_email(email: str) -> Optional[User]:
    """Retrieves a user by their email from the JSON file."""
    users = await _read_users_from_file()
    for user_data in users:
        if user_data["email"] == email:
            return User(**user_data)
    return None

async def get_users(skip: int = 0, limit: int = 100) -> List[User]:
    """Retrieves a list of users from the JSON file with pagination."""
    users = await _read_users_from_file()
    paginated_users = users[skip : skip + limit]
    return [User(**user_data) for user_data in paginated_users]

async def create_user(user: UserCreate) -> User:
    """Creates a new user and saves it to the JSON file."""
    users = await _read_users_from_file()
    
    # Check if user already exists
    if any(u["email"] == user.email for u in users):
        raise ValueError("Email already registered")

    hashed_password = get_password_hash(user.password)
    new_user_id = max([u["id"] for u in users] or [0]) + 1
    
    new_user_data = {
        "id": new_user_id,
        "name": user.name,
        "email": user.email,
        "hashed_password": hashed_password,
        "role": user.role
    }
    
    users.append(new_user_data)
    await _write_users_to_file(users)
    
    return User(**new_user_data)

async def delete_user(user_id: int) -> Optional[User]:
    """Deletes a user by their ID from the JSON file."""
    users = await _read_users_from_file()
    user_to_delete = None
    updated_users = []
    
    for user_data in users:
        if user_data["id"] == user_id:
            user_to_delete = User(**user_data)
        else:
            updated_users.append(user_data)

    if user_to_delete:
        await _write_users_to_file(updated_users)
        
    return user_to_delete