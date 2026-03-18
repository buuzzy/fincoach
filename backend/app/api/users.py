"""User API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.core.auth import get_current_user
from app.models import (
    UserORM,
    TradeORM,
    MarketDataORM,
    TradeRecord,
    MarketData,
    UserListItem,
    UserProfile,
)
from app.services.profiler import analyze_user_profile

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/", response_model=list[UserListItem])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """List all users with trade counts."""
    stmt = (
        select(
            UserORM,
            func.count(TradeORM.id).label("trade_count"),
        )
        .outerjoin(TradeORM, UserORM.id == TradeORM.user_id)
        .group_by(UserORM.id)
        .order_by(UserORM.id)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [
        UserListItem(
            id=user.id,
            name=user.name,
            profile_type=user.profile_type,
            trade_count=trade_count,
        )
        for user, trade_count in rows
    ]


@router.get("/{user_id}/profile", response_model=UserProfile)
async def get_user_profile(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Generate and return user profile analysis."""
    user = await db.get(UserORM, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    stmt = (
        select(TradeORM)
        .where(TradeORM.user_id == user_id)
        .order_by(TradeORM.trade_time)
    )
    result = await db.execute(stmt)
    trade_orms = result.scalars().all()
    trades = [TradeRecord.model_validate(t) for t in trade_orms]

    profile = analyze_user_profile(trades, user.id, user.name)
    return profile
