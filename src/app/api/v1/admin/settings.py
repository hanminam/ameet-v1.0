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
    
    # DB에 설정이 없고, 요청된 키가 'default_agent_prompt'일 경우,
    # 하드코딩된 기본값을 만들어서 반환합니다.
    if not setting and setting_key == "default_agent_prompt":
        print("--- [Admin API] DB에 설정이 없어 기본 프롬프트 값을 반환합니다. ---")
        
        # orchestrator.py에 있는 것과 동일한 기본 프롬프트 값
        fallback_prompt = (
            "당신의 역할은 '{role}'이며 지정된 역할 관점에서 말하세요.\n"
            "당신의 역할에 맞는 대화스타일을 사용하세요.\n"
            "토의 규칙을 숙지하고 토론의 목표를 달성하기 위해 제시된 의견들을 바탕으로 보완의견을 제시하거나, 주장을 강화,철회,수정 하세요.\n"
            "모든 의견은 논리적이고 일관성이 있어야 하며 신뢰할 수 있는 출처에 기반해야하고 자세하게 답변하여야 합니다.\n"
            "사용자가 질문한 언어로 답변하여야 합니다."
        )
        # DB에 저장하지 않고, 화면에 보여주기 위한 임시 객체를 생성하여 반환
        return SystemSettings(
            key=setting_key,
            value=fallback_prompt,
            description="Jury Selector가 동적으로 에이전트를 생성할 때 사용하는 기본 프롬프트 템플릿. '{role}' 변수를 포함해야 합니다."
        )

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