"""Shared trade utilities — pair matching & market data helpers.

Used by pattern, backtest, and trades API modules.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import TypeVar, Generator

from app.models import MarketData, TradeDirection

T = TypeVar("T")


def pair_trades(trades: list[T]) -> Generator[tuple[T, T], None, None]:
    """Match buy→sell pairs for the same stock in chronological order.

    Works with both TradeORM and TradeRecord (Pydantic) objects.
    """
    buys: dict[str, list[T]] = defaultdict(list)
    for t in sorted(trades, key=lambda x: x.trade_time):  # type: ignore[attr-defined]
        if t.direction == TradeDirection.BUY:  # type: ignore[attr-defined]
            buys[t.stock_code].append(t)  # type: ignore[attr-defined]
        elif t.direction == TradeDirection.SELL and buys.get(t.stock_code):  # type: ignore[attr-defined]
            yield buys[t.stock_code].pop(0), t  # type: ignore[attr-defined]


def build_price_map(
    market_data: list[MarketData],
) -> dict[str, list[MarketData]]:
    """Return market data sorted by date, keyed by stock_code."""
    by_stock: dict[str, list[MarketData]] = defaultdict(list)
    for md in market_data:
        by_stock[md.stock_code].append(md)
    for code in by_stock:
        by_stock[code].sort(key=lambda m: m.trade_date)
    return by_stock


def get_avg_close(
    price_list: list[MarketData],
    target_date: date,
    window: int = 5,
) -> float | None:
    """Return average close of *window* trading days before target_date."""
    closes = [m.close_price for m in price_list if m.trade_date < target_date]
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def get_future_close(
    price_list: list[MarketData],
    target_date: date,
    days_ahead: int = 5,
) -> float | None:
    """Return the close price *days_ahead* trading days after target_date."""
    future = [m for m in price_list if m.trade_date > target_date]
    if len(future) < days_ahead:
        return None
    return future[days_ahead - 1].close_price
