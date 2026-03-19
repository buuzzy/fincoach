"""Auth API routes — simple login, no JWT."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.auth import check_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool = True


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    """验证固定账号密码，成功返回 {ok: true}，无 token。"""
    check_password(body.username, body.password)
    return LoginResponse()
