# src/app/api/v1/admin/settings.py

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional
from pydantic import BaseModel

from app.models.discussion import SystemSettings
from app.api.v1.users import get_current_admin_user
from app.models.user import User as UserModel

router = APIRouter()

class SettingUpdatePayload(BaseModel):
    value: str

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
    setting = await SystemSettings.find_one(SystemSettings.key == setting_key)
    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setting with key '{setting_key}' not found."
        )
    return setting

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
    setting = await SystemSettings.find_one(SystemSettings.key == setting_key)
    if setting:
        setting.value = payload.value
        await setting.save()
    else:
        setting = SystemSettings(key=setting_key, value=payload.value)
        await setting.insert()
    
    return setting