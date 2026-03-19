"""Auth utilities — simple password check, no JWT."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.core.config import get_settings


def check_password(username: str, password: str) -> None:
    """Raise 401 if credentials do not match the configured fixed account."""
    settings = get_settings()
    if username != settings.APP_USERNAME or password != settings.APP_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码错误",
        )
