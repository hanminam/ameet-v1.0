# app/models/discussion.py
from beanie import Document
from pydantic import BaseModel
from typing import List, Dict, Any

class DiscussionLog(Document):
    # beanie.Document를 상속받으면 자동으로 MongoDB 컬렉션 모델이 됩니다.
    topic: str
    user_email: str
    transcript: List[Dict[str, Any]]

    class Settings:
        # 사용할 컬렉션 이름
        name = "discussions"

class AgentSettings(Document):
    name: str
    prompt: str
    model: str
    temperature: float
    tools: List[str] = []

    class Settings:
        name = "agents"