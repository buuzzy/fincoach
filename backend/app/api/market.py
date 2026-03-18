"""Market data API routes — serve local K-line data for frontend charts."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.core.auth import get_current_user
from app.models import MarketDataORM, CandleBar, MarketDataResponse

router = APIRouter(prefix="/api/market-data", tags=["market"])


@router.get("/{stock_code}", response_model=MarketDataResponse)
async def get_market_data(
    stock_code: str,
    start: str,
    end: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Return OHLCV candle bars for a stock within a date range.

    Query params:
        start: YYYY-MM-DD
        end:   YYYY-MM-DD
    """
    # Parse to date objects so PostgreSQL DATE comparison works correctly
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式错误，请使用 YYYY-MM-DD")

    stmt = (
        select(MarketDataORM)
        .where(
            MarketDataORM.stock_code == stock_code,
            MarketDataORM.trade_date >= start_date,
            MarketDataORM.trade_date <= end_date,
        )
        .order_by(MarketDataORM.trade_date)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    if not rows:
        raise HTTPException(status_code=404, detail="No market data found for this stock and date range")

    return MarketDataResponse(
        stock_code=stock_code,
        stock_name=rows[0].stock_name,
        bars=[
            CandleBar(
                date=str(r.trade_date),
                open=r.open_price,
                high=r.high_price,
                low=r.low_price,
                close=r.close_price,
                volume=r.volume,
            )
            for r in rows
        ],
    )
