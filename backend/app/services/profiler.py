"""User profile identification service."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from app.models import (
    TradeRecord,
    TradeDirection,
    UserProfile,
    UserProfileType,
)


def analyze_user_profile(
    trades: list[TradeRecord],
    user_id: int,
    user_name: str,
) -> UserProfile:
    """Analyze trading history and classify user into a profile type."""

    if not trades:
        return UserProfile(
            user_id=user_id,
            user_name=user_name,
            profile_type=UserProfileType.BALANCED,
            trade_count=0,
            win_rate=0.0,
            avg_holding_days=0.0,
            total_pnl=0.0,
            avg_pnl_per_trade=0.0,
            max_single_loss=0.0,
            max_single_gain=0.0,
            trade_frequency_per_week=0.0,
        )

    # --- basic metrics from sell trades (they carry pnl) ---
    sell_trades = [t for t in trades if t.direction == TradeDirection.SELL and t.pnl is not None]
    trade_count = len(sell_trades)

    wins = sum(1 for t in sell_trades if t.pnl > 0)
    win_rate = wins / trade_count if trade_count else 0.0

    total_pnl = sum(t.pnl for t in sell_trades)
    avg_pnl_per_trade = total_pnl / trade_count if trade_count else 0.0

    pnl_values = [t.pnl for t in sell_trades]
    max_single_loss = min(pnl_values) if pnl_values else 0.0
    max_single_gain = max(pnl_values) if pnl_values else 0.0

    # --- holding days: pair buy/sell by stock_code chronologically ---
    buys_by_stock: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in sorted(trades, key=lambda x: x.trade_time):
        if t.direction == TradeDirection.BUY:
            buys_by_stock[t.stock_code].append(t)

    holding_days_list: list[float] = []
    for t in sorted(trades, key=lambda x: x.trade_time):
        if t.direction == TradeDirection.SELL and buys_by_stock[t.stock_code]:
            buy_trade = buys_by_stock[t.stock_code].pop(0)
            delta = (t.trade_time - buy_trade.trade_time).total_seconds() / 86400.0
            holding_days_list.append(max(delta, 0.0))

    avg_holding_days = (
        sum(holding_days_list) / len(holding_days_list) if holding_days_list else 0.0
    )

    # --- trade frequency per week ---
    all_times = [t.trade_time for t in trades]
    if len(all_times) >= 2:
        span_days = (max(all_times) - min(all_times)).total_seconds() / 86400.0
        weeks = max(span_days / 7.0, 1.0)
        trade_frequency_per_week = len(trades) / weeks
    else:
        trade_frequency_per_week = float(len(trades))

    # --- classify profile type ---
    # Count chase-high heuristic: buys where price > 5% above recent average
    chase_high_count = 0
    slow_stop_count = 0
    for t in trades:
        if t.direction == TradeDirection.BUY:
            # simplified heuristic – we don't have market context here,
            # so treat any buy whose pnl_pct ends < -10% as a chase-high proxy
            pass
        if t.direction == TradeDirection.SELL and t.pnl_pct is not None:
            if t.pnl_pct < -10:
                slow_stop_count += 1

    # Chase-high proxy: count buy trades followed by a sell with negative pnl
    buy_sell_pairs = []
    temp_buys: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in sorted(trades, key=lambda x: x.trade_time):
        if t.direction == TradeDirection.BUY:
            temp_buys[t.stock_code].append(t)
        elif t.direction == TradeDirection.SELL and temp_buys[t.stock_code]:
            buy_t = temp_buys[t.stock_code].pop(0)
            if t.pnl is not None and t.pnl < 0:
                chase_high_count += 1

    emotional_signals = chase_high_count + slow_stop_count

    if trade_frequency_per_week > 3 and win_rate < 0.45:
        profile_type = UserProfileType.AGGRESSIVE
    elif emotional_signals >= max(3, trade_count * 0.3):
        profile_type = UserProfileType.EMOTIONAL
    elif avg_holding_days > 15 or (win_rate > 0.5 and avg_pnl_per_trade < 200):
        profile_type = UserProfileType.CONSERVATIVE
    else:
        profile_type = UserProfileType.BALANCED

    return UserProfile(
        user_id=user_id,
        user_name=user_name,
        profile_type=profile_type,
        trade_count=trade_count,
        win_rate=round(win_rate, 4),
        avg_holding_days=round(avg_holding_days, 2),
        total_pnl=round(total_pnl, 2),
        avg_pnl_per_trade=round(avg_pnl_per_trade, 2),
        max_single_loss=round(max_single_loss, 2),
        max_single_gain=round(max_single_gain, 2),
        trade_frequency_per_week=round(trade_frequency_per_week, 2),
    )
