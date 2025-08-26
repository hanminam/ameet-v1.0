# src/app/api/v1/discussions.py

from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

from app.api.v1.users import get_current_user
from app.models.user import User as UserModel
from app.models.discussion import DiscussionLog
from app.schemas.discussion import DiscussionLogItem, DiscussionLogDetail

router = APIRouter()

@router.get(
    "/",
    response_model=List[DiscussionLogItem],
    summary="나의 토론 이력 목록 조회"
)
async def get_my_discussions(
    current_user: UserModel = Depends(get_current_user)
):
    """
    현재 로그인한 사용자의 모든 토론 이력 목록을 최신순으로 반환합니다.
    """
    discussions = await DiscussionLog.find(
        DiscussionLog.user_email == current_user.email
    ).sort(-DiscussionLog.created_at).to_list()
    
    return discussions

@router.get(
    "/{discussion_id}",
    response_model=DiscussionLogDetail,
    summary="특정 토론 상세 조회"
)
async def get_discussion_detail(
    discussion_id: str,
    current_user: UserModel = Depends(get_current_user)
):
    """
    특정 토론의 상세 내용을 조회합니다.
    자신이 생성한 토론이 아닐 경우 접근이 거부됩니다.
    """
    discussion = await DiscussionLog.find_one(DiscussionLog.discussion_id == discussion_id)
    
    if not discussion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discussion not found.")
        
    if discussion.user_email != current_user.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this discussion.")
        
    return discussion