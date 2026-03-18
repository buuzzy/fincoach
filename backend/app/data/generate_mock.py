"""Mock data generator — real K-line backed trades.

Flow
----
1. Call QVeris ``ths_ifind.history_quotation.v1`` for each stock to fetch
   actual OHLCV for the seed period.
2. Build trades whose buy/sell prices sit inside the real daily High/Low range.
3. Persist both ``market_data`` and ``trades`` to the database.

Fallback
--------
If QVeris is unavailable (no key, quota exhausted, network error) the generator
falls back to synthetic price walks so the app remains runnable.  A clear
WARNING is logged so the developer knows the data is not real.

Stock-code format
-----------------
All codes use the ``NNNNNN.XX`` format (e.g. ``600519.SH``, ``000858.SZ``) to
match QVeris conventions.  The ``SH``/``SZ`` suffix is derived from the numeric
prefix: codes starting with ``6`` are Shanghai (SH); all others are Shenzhen (SZ).
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, date, timedelta
from typing import Any

from app.core import get_async_session
from app.models import (
    UserORM,
    TradeORM,
    MarketDataORM,
    UserProfileType,
    TradeDirection,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# (code_with_suffix, chinese_name)
STOCKS: list[tuple[str, str]] = [
    ("600519.SH", "贵州茅台"),
    ("000858.SZ", "五粮液"),
    ("601318.SH", "中国平安"),
    ("000333.SZ", "美的集团"),
    ("600036.SH", "招商银行"),
    ("002594.SZ", "比亚迪"),
    ("601888.SH", "中国中免"),
    ("000651.SZ", "格力电器"),
    ("600900.SH", "长江电力"),
    ("002415.SZ", "海康威视"),
]

USERS: list[tuple[str, UserProfileType]] = [
    ("张伟", UserProfileType.AGGRESSIVE),
    ("李静", UserProfileType.CONSERVATIVE),
    ("王磊", UserProfileType.EMOTIONAL),
    ("陈敏", UserProfileType.BALANCED),
    ("赵新", UserProfileType.BALANCED),
]

PERIOD_START = date(2025, 1, 2)
PERIOD_END   = date(2025, 3, 31)

# Commission rate (双边, 买+卖): 万分之三 each way; stamp duty 0.1% on sell side
COMMISSION_RATE = 0.0003
STAMP_DUTY_RATE = 0.001  # sell only

# QVeris tool for history quotation
_KLINE_TOOL_QUERY = "A股历史K线日线数据"
_KLINE_TOOL_ID    = "ths_ifind.history_quotation.v1"


# ── Utility ───────────────────────────────────────────────────────────────────

def _trading_days(start: date, end: date) -> list[date]:
    days, cur = [], start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


def _suffix(code_bare: str) -> str:
    return "SH" if code_bare.startswith("6") else "SZ"


# ── QVeris K-line fetch ───────────────────────────────────────────────────────

async def _fetch_kline_from_qveris(code: str) -> list[dict[str, Any]]:
    """Fetch daily K-line from QVeris for *code* (e.g. ``600519.SH``).

    QVeris response shape for ths_ifind.history_quotation.v1:
      {
        "success": true,
        "result": {
          "data": [
            [  ← outer list = rows
              {
                "thscode": "600519.SH",
                "time": "2025-01-02",
                "open": 1524, "high": 1524.49, "low": 1480, "close": 1488,
                "volume": 5002870, "changeRatio": -2.36, ...
              },
              ...
            ]
          ]
        }
      }

    Returns a list of row dicts with keys: date, open, high, low, close, volume, change_pct
    """
    from app.services.qveris_client import get_key_pool

    pool = get_key_pool()

    # Search specifically for ths_ifind tool (Chinese name hits it as top result)
    _tool_id, search_id = await pool.search("iFinD 同花顺历史行情", preferred_tool_id=_KLINE_TOOL_ID)

    # Always execute against the known validated tool_id
    params = {
        "codes": code,
        "indicators": "open,high,low,close,volume,changeRatio",
        "startdate": PERIOD_START.strftime("%Y-%m-%d"),
        "enddate":   PERIOD_END.strftime("%Y-%m-%d"),
        "interval":  "D",
    }
    resp = await pool.execute(_KLINE_TOOL_ID, search_id, params)

    # ── Validate execute result ───────────────────────────────────────────────
    if not resp.get("success"):
        err = resp.get("error_message", "unknown error")
        logger.warning("[seed] QVeris execute failed for %s: %s", code, err)
        return []

    result_payload = resp.get("result", {})
    raw_data = result_payload.get("data") if isinstance(result_payload, dict) else resp.get("data")

    # ── Normalise response shape ──────────────────────────────────────────────
    # ths_ifind returns data as list[list[dict]] where inner list = all rows for that code
    row_list: list[dict[str, Any]] = []
    if isinstance(raw_data, list):
        for item in raw_data:
            if isinstance(item, list):
                row_list.extend(item)      # unwrap inner list
            elif isinstance(item, dict):
                row_list.append(item)
    elif isinstance(raw_data, dict):
        row_list = list(raw_data.values())[0] if raw_data else []

    normalised: list[dict[str, Any]] = []
    for r in row_list:
        try:
            d_raw = r.get("time") or r.get("date") or r.get("trade_date")
            if d_raw is None:
                continue
            d = date.fromisoformat(str(d_raw)[:10])

            normalised.append({
                "date":       d,
                "open":       float(r.get("open")  or r.get("open_price",  0)),
                "high":       float(r.get("high")  or r.get("high_price",  0)),
                "low":        float(r.get("low")   or r.get("low_price",   0)),
                "close":      float(r.get("close") or r.get("close_price", 0)),
                "volume":     float(r.get("volume") or r.get("vol", 0)),
                "change_pct": float(r.get("changeRatio") or r.get("change_pct") or r.get("pct_chg", 0)),
            })
        except (TypeError, ValueError) as exc:
            logger.debug("[seed] Skipping malformed row for %s: %s", code, exc)
            continue

    logger.info("[seed] QVeris returned %d rows for %s", len(normalised), code)
    return normalised


# ── Synthetic fallback ────────────────────────────────────────────────────────

_SEED_PRICES: dict[str, float] = {
    "600519.SH": 1700.0, "000858.SZ": 150.0, "601318.SH": 48.0,
    "000333.SZ": 58.0,   "600036.SH": 35.0,  "002594.SZ": 250.0,
    "601888.SH": 80.0,   "000651.SZ": 38.0,  "600900.SH": 26.0,
    "002415.SZ": 32.0,
}


def _synthetic_kline(code: str) -> list[dict[str, Any]]:
    """Generate a random-walk K-line series as fallback."""
    rng = random.Random(hash(code) & 0xFFFFFFFF)
    price = _SEED_PRICES.get(code, 50.0)
    rows: list[dict[str, Any]] = []
    for d in _trading_days(PERIOD_START, PERIOD_END):
        chg = max(min(rng.gauss(0, 2.0), 10.0), -10.0)
        close = round(price * (1 + chg / 100), 2)
        high  = round(max(price, close) * (1 + rng.uniform(0, 0.015)), 2)
        low   = round(min(price, close) * (1 - rng.uniform(0, 0.015)), 2)
        opn   = round(price + rng.uniform(-0.5, 0.5) * price * 0.01, 2)
        vol   = round(rng.uniform(50000, 500000) * (price / 50), 0)
        rows.append({
            "date": d, "open": opn, "high": high, "low": low,
            "close": close, "volume": vol,
            "change_pct": round(chg, 2),
        })
        price = close
    return rows


# ── Market-data ORM builder ───────────────────────────────────────────────────

def _to_market_orm(code: str, name: str, row: dict[str, Any]) -> MarketDataORM:
    return MarketDataORM(
        stock_code=code,
        stock_name=name,
        trade_date=row["date"],
        open_price=row["open"],
        high_price=row["high"],
        low_price=row["low"],
        close_price=row["close"],
        volume=row["volume"],
        change_pct=row["change_pct"],
    )


# ── Trade generator (profile-aware, price-realistic) ─────────────────────────

def _generate_trades(
    user_id: int,
    profile_type: UserProfileType,
    kline_map: dict[str, list[dict[str, Any]]],
) -> list[TradeORM]:
    """Generate buy+sell pairs that respect real daily High/Low ranges."""

    rng = random.Random(user_id * 1000 + hash(profile_type.value) & 0xFF)

    profile_cfg = {
        UserProfileType.AGGRESSIVE:  dict(trips=(30, 40), hold=(1,  5),  buy_premium=(1.01, 1.05), sell_noise=(-0.02, 0.02)),
        UserProfileType.CONSERVATIVE:dict(trips=(12, 18), hold=(15, 35), buy_premium=(0.98, 1.02), sell_noise=(-0.01, 0.01)),
        UserProfileType.EMOTIONAL:   dict(trips=(25, 35), hold=(2,  25), buy_premium=(1.02, 1.07), sell_noise=(-0.02, 0.01)),
        UserProfileType.BALANCED:    dict(trips=(18, 25), hold=(3,  15), buy_premium=(0.99, 1.02), sell_noise=(-0.01, 0.01)),
    }
    cfg = profile_cfg[profile_type]

    # Stocks available to this user
    available = list(kline_map.keys())
    user_stocks = rng.sample(available, k=min(rng.randint(4, 7), len(available)))

    n_trips = rng.randint(*cfg["trips"])
    trades: list[TradeORM] = []

    for _ in range(n_trips):
        code = rng.choice(user_stocks)
        rows = kline_map[code]
        if len(rows) < 5:
            continue

        hold_days = rng.randint(*cfg["hold"])
        buy_idx   = rng.randint(3, max(4, len(rows) - hold_days - 3))
        sell_idx  = min(buy_idx + hold_days, len(rows) - 1)
        if sell_idx <= buy_idx:
            continue

        buy_row  = rows[buy_idx]
        sell_row = rows[sell_idx]

        # ── Buy price: between low and high of buy day, biased by profile ────
        buy_lo, buy_hi = buy_row["low"], buy_row["high"]
        premium = rng.uniform(*cfg["buy_premium"])
        raw_buy = buy_row["close"] * premium
        buy_price = round(max(buy_lo, min(buy_hi, raw_buy)), 2)

        # ── Sell price: within sell day's range ───────────────────────────────
        sell_lo, sell_hi = sell_row["low"], sell_row["high"]
        noise = rng.uniform(*cfg["sell_noise"])
        raw_sell = sell_row["close"] * (1 + noise)
        sell_price = round(max(sell_lo, min(sell_hi, raw_sell)), 2)

        quantity = rng.choice([100, 200, 300, 500, 1000])

        # ── P&L including commission and stamp duty ───────────────────────────
        buy_cost  = buy_price  * quantity * (1 + COMMISSION_RATE)
        sell_recv = sell_price * quantity * (1 - COMMISSION_RATE - STAMP_DUTY_RATE)
        pnl       = round(sell_recv - buy_cost, 2)
        pnl_pct   = round((sell_price - buy_price) / buy_price * 100, 2)

        # Find the actual stock name from STOCKS list
        stock_name = next((n for c, n in STOCKS if c == code), code)

        buy_time  = datetime.combine(
            buy_row["date"],
            datetime.min.time().replace(hour=rng.randint(9, 14), minute=rng.randint(30, 59)),
        )
        sell_time = datetime.combine(
            sell_row["date"],
            datetime.min.time().replace(hour=rng.randint(9, 14), minute=rng.randint(30, 59)),
        )

        trades.append(TradeORM(
            user_id=user_id, stock_code=code, stock_name=stock_name,
            direction=TradeDirection.BUY, price=buy_price, quantity=quantity,
            trade_time=buy_time, pnl=None, pnl_pct=None,
        ))
        trades.append(TradeORM(
            user_id=user_id, stock_code=code, stock_name=stock_name,
            direction=TradeDirection.SELL, price=sell_price, quantity=quantity,
            trade_time=sell_time, pnl=pnl, pnl_pct=pnl_pct,
        ))

    return trades


def _generate_zhaoxin_trades(
    user_id: int,
    kline_map: dict[str, list[dict[str, Any]]],
) -> list[TradeORM]:
    """Generate only 6-8 trades for 赵新 to trigger data_warning=insufficient.

    Includes at least 1 slow_stop_loss trade (pnl < -8%) and 1 chase_high trade
    (buy price > avg5 * 1.05) to ensure patterns are detected.
    """
    rng = random.Random(user_id * 7777)

    # Use 2 stocks from available klines
    available = list(kline_map.keys())
    user_stocks = rng.sample(available, k=min(2, len(available)))
    trades: list[TradeORM] = []

    def _add_pair(code: str, buy_idx: int, sell_idx: int,
                  buy_price_override: float | None = None,
                  sell_price_override: float | None = None) -> None:
        rows = kline_map.get(code, [])
        if not rows or sell_idx >= len(rows) or buy_idx >= sell_idx:
            return
        stock_name = next((n for c, n in STOCKS if c == code), code)
        buy_row = rows[buy_idx]
        sell_row = rows[sell_idx]

        buy_price = buy_price_override if buy_price_override else round(
            max(buy_row["low"], min(buy_row["high"], buy_row["close"] * 1.01)), 2
        )
        sell_price = sell_price_override if sell_price_override else round(
            max(sell_row["low"], min(sell_row["high"], sell_row["close"] * 0.99)), 2
        )
        quantity = 300

        buy_cost = buy_price * quantity * (1 + COMMISSION_RATE)
        sell_recv = sell_price * quantity * (1 - COMMISSION_RATE - STAMP_DUTY_RATE)
        pnl = round(sell_recv - buy_cost, 2)
        pnl_pct = round((sell_price - buy_price) / buy_price * 100, 2)

        buy_time = datetime.combine(
            buy_row["date"],
            datetime.min.time().replace(hour=10, minute=30),
        )
        sell_time = datetime.combine(
            sell_row["date"],
            datetime.min.time().replace(hour=14, minute=0),
        )

        trades.append(TradeORM(
            user_id=user_id, stock_code=code, stock_name=stock_name,
            direction=TradeDirection.BUY, price=buy_price, quantity=quantity,
            trade_time=buy_time, pnl=None, pnl_pct=None,
        ))
        trades.append(TradeORM(
            user_id=user_id, stock_code=code, stock_name=stock_name,
            direction=TradeDirection.SELL, price=sell_price, quantity=quantity,
            trade_time=sell_time, pnl=pnl, pnl_pct=pnl_pct,
        ))

    code0 = user_stocks[0] if user_stocks else available[0]
    code1 = user_stocks[1] if len(user_stocks) > 1 else code0
    rows0 = kline_map.get(code0, [])
    rows1 = kline_map.get(code1, [])

    # Trade 1: slow_stop_loss — buy at high price, sell at big loss (-10%)
    if len(rows0) >= 30:
        buy_price = round(rows0[5]["close"] * 1.03, 2)
        sell_price = round(buy_price * 0.88, 2)  # -12% loss → triggers slow_stop_loss
        sell_price = round(max(rows0[20]["low"], min(rows0[20]["high"], sell_price)), 2)
        _add_pair(code0, 5, 20, buy_price, sell_price)

    # Trade 2: chase_high — buy at significantly above avg5 price
    if len(rows0) >= 50:
        avg5 = sum(r["close"] for r in rows0[22:27]) / 5
        buy_price = round(avg5 * 1.08, 2)  # 8% above avg5 → triggers chase_high
        buy_price = round(max(rows0[27]["low"], min(rows0[27]["high"], buy_price)), 2)
        sell_price = round(rows0[35]["close"] * 0.98, 2)
        _add_pair(code0, 27, 35, buy_price, sell_price)

    # Trade 3: normal losing trade
    if len(rows1) >= 40:
        _add_pair(code1, 8, 18)

    # Trades 4-6 (or up to 8): add 1-3 more normal trades
    n_extra = rng.randint(1, 3)
    for i in range(n_extra):
        base = 40 + i * 8
        if len(rows1) > base + 5:
            _add_pair(code1, base, base + 5)

    return trades


# ── Top-level orchestration ───────────────────────────────────────────────────

async def _fetch_all_klines() -> dict[str, list[dict[str, Any]]]:
    """Fetch real K-line for all stocks; fallback per-stock on error."""
    # Check whether QVeris pool is available
    qveris_available = False
    try:
        from app.services.qveris_client import get_key_pool
        pool = get_key_pool()
        qveris_available = pool.available_count > 0
    except Exception:
        pass

    kline_map: dict[str, list[dict[str, Any]]] = {}

    for code, name in STOCKS:
        if qveris_available:
            try:
                rows = await _fetch_kline_from_qveris(code)
                if rows:
                    kline_map[code] = rows
                    continue
                else:
                    logger.warning("[seed] QVeris returned 0 rows for %s — using synthetic fallback", code)
            except Exception as exc:
                logger.warning("[seed] QVeris failed for %s (%s) — using synthetic fallback", code, exc)
        else:
            logger.warning("[seed] QVeris pool unavailable — using synthetic K-line for %s", code)

        kline_map[code] = _synthetic_kline(code)

    return kline_map


def generate_mock_data_sync() -> tuple[list[UserORM], list[TradeORM], list[MarketDataORM]]:
    """Synchronous entry point (runs the async version in a new event loop).

    Only used for quick CLI testing.  In production use ``seed_database()``.
    """
    return asyncio.run(_generate_mock_data_async())


async def _generate_mock_data_async() -> tuple[list[UserORM], list[TradeORM], list[MarketDataORM]]:
    users = [
        UserORM(id=i + 1, name=name, profile_type=ptype)
        for i, (name, ptype) in enumerate(USERS)
    ]

    kline_map = await _fetch_all_klines()

    # Build market_data ORM rows
    market_records: list[MarketDataORM] = []
    for code, name in STOCKS:
        rows = kline_map.get(code, [])
        for row in rows:
            market_records.append(_to_market_orm(code, name, row))

    # Build trade ORM rows per user
    all_trades: list[TradeORM] = []
    for user in users:
        if user.name == "赵新":
            trades = _generate_zhaoxin_trades(user.id, kline_map)
        else:
            trades = _generate_trades(user.id, user.profile_type, kline_map)
        all_trades.extend(trades)

    logger.info(
        "[seed] Generated %d users, %d trades, %d market_data rows.",
        len(users), len(all_trades), len(market_records),
    )
    return users, all_trades, market_records


async def seed_database() -> None:
    """Insert all mock data into the database (called from main.py lifespan)."""
    users, trades, market_data = await _generate_mock_data_async()

    async with get_async_session()() as session:
        async with session.begin():
            session.add_all(users)
        await session.commit()

        async with session.begin():
            session.add_all(market_data)
        await session.commit()

        async with session.begin():
            session.add_all(trades)
        await session.commit()

    logger.info("[seed] Database seeded successfully.")
