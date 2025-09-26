# src/app/api/v1/admin/settings.py

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional
from pydantic import BaseModel

from app.models.discussion import SystemSettings
from app.api.v1.users import get_current_admin_user
from app.models.user import User as UserModel
from app import db
from app.core.config import settings

router = APIRouter()

class SettingUpdatePayload(BaseModel):
    value: str

# DB 컬렉션을 가져오는 헬퍼 함수
def get_settings_collection():
    db_name = settings.MONGO_DB_URL.split("/")[-1].split("?")[0]
    return db.mongo_client[db_name]["system_settings"]

@router.get(
    "/{setting_key}",
    response_model=SystemSettings,
    summary="특정 시스템 설정 조회"
)
async def get_setting(
    setting_key: str,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """지정된 key에 해당하는 시스템 설정을 DB에서 조회합니다."""
    # Beanie 대신 motor 드라이버 사용
    collection = get_settings_collection()
    setting_data = await collection.find_one({"key": setting_key})
    
    if not setting_data and setting_key == "default_agent_prompt":
        fallback_prompt = (
            "당신의 역할은 '{role}'이며 지정된 역할 관점에서 말하세요.\n"
            "당신의 역할에 맞는 대화스타일을 사용하세요.\n"
            "토의 규칙을 숙지하고 토론의 목표를 달성하기 위해 제시된 의견들을 바탕으로 보완의견을 제시하거나, 주장을 강화,철회,수정 하세요.\n"
            "모든 의견은 논리적이고 일관성이 있어야 하며 신뢰할 수 있는 출처에 기반해야하고 자세하게 답변하여야 합니다.\n"
            "사용자가 질문한 언어로 답변하여야 합니다."
        )
        return SystemSettings(key=setting_key, value=fallback_prompt)

    if not setting_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setting with key '{setting_key}' not found."
        )
    return SystemSettings.model_validate(setting_data)

@router.put(
    "/{setting_key}",
    response_model=SystemSettings,
    summary="특정 시스템 설정 수정 또는 생성"
)
async def update_setting(
    setting_key: str,
    payload: SettingUpdatePayload,
    admin_user: UserModel = Depends(get_current_admin_user)
):
    """
    지정된 key의 시스템 설정을 업데이트합니다.
    만약 해당 key의 설정이 존재하지 않으면 새로 생성합니다.
    """
    # Beanie 대신 motor 드라이버 사용
    collection = get_settings_collection()
    
    # MongoDB의 find_one_and_update는 upsert 옵션을 통해 문서를 한번에 처리할 수 있습니다.
    updated_document = await collection.find_one_and_update(
        {"key": setting_key},
        {"$set": {
            "value": payload.value,
            "key": setting_key # upsert 시 key 필드도 생성되도록 추가
        }},
        upsert=True, # 문서가 없으면 새로 생성(insert)
        return_document=True # 업데이트 후의 문서를 반환
    )
    return SystemSettings.model_validate(updated_document)