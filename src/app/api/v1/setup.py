# src/app/api/v1/setup.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.schemas import user as user_schema
from app import crud

router = APIRouter()

@router.get("/initial-users", response_model=dict)
async def create_initial_users():
    """
    Creates initial admin and user accounts in the users.json file.
    (Warning: This endpoint should be disabled or removed in a production environment.)
    """
    
    actions_log = []

    # --- Admin User Info ---
    admin_user_email = "admin@example.com"
    admin_user_password = "adminpassword"
    
    admin_user = await crud.user.get_user_by_email(email=admin_user_email)
    if not admin_user:
        user_in = user_schema.UserCreate(
            name="Admin User",
            email=admin_user_email,
            password=admin_user_password,
            role="admin"
        )
        await crud.user.create_user(user_in)
        actions_log.append(f"Admin user '{admin_user_email}' created.")
    else:
        actions_log.append(f"Admin user '{admin_user_email}' already exists.")

    # --- Normal User Info ---
    normal_user_email = "user@example.com"
    normal_user_password = "userpassword"

    normal_user = await crud.user.get_user_by_email(email=normal_user_email)
    if not normal_user:
        user_in = user_schema.UserCreate(
            name="Normal User",
            email=normal_user_email,
            password=normal_user_password,
            role="user"
        )
        await crud.user.create_user(user_in)
        actions_log.append(f"Normal user '{normal_user_email}' created.")
    else:
        actions_log.append(f"Normal user '{normal_user_email}' already exists.")

    return {"status": "success", "actions": actions_log}
