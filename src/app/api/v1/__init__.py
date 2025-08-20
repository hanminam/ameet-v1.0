# src/app/api/v1/__init__.py

from fastapi import APIRouter

from . import login, users, setup

api_router = APIRouter()
api_router.include_router(login.router, prefix="/login", tags=["login"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(setup.router, prefix="/setup", tags=["setup"])