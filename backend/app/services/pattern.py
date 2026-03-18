"""Pattern recognition engine — detects 5 core trading anti-patterns."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from app.models import (
    TradeRecord,
    MarketData,
    TradeDirection,
    PatternType,
    PatternResult,
)


def _build_price_map(
    market_data: list[MarketData],
) -> dict[str, list[MarketData]]:
    """Return market data sorted by date, keyed by stock_code."""
    by_stock: dict[str, list[MarketData]] = defaultdict(list)
    for md in market_data:
        by_stock[md.stock_code].append(md)
    for code in by_stock:
        by_stock[code].sort(key=lambda m: m.trade_date)
    return by_stock


def _get_avg_close(
    price_list: list[MarketData],
    target_date,
    window: int = 5,
) -> float | None:
    """Return average close of *window* trading days up to (not including) target_date."""
    closes = [m.close_price for m in price_list if m.trade_date < target_date]
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _get_future_close(
    price_list: list[MarketData],
    target_date,
    days_ahead: int = 5,
) -> float | None:
    """Return the close price *days_ahead* trading days after target_date."""
    future = [m for m in price_list if m.trade_date > target_date]
    if len(future) < days_ahead:
        return None
    return future[days_ahead - 1].close_price


def _get_close_on_date(
    price_list: list[MarketData],
    target_date,
) -> float | None:
    for m in price_list:
        if m.trade_date == target_date:
            return m.close_price
    return None


# ─── pair buy/sell helper ───────────────────────────────────────────
def _pair_trades(trades: list[TradeRecord]):
    """Yield (buy, sell) pairs matched by stock_code chronologically."""
    buys: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in sorted(trades, key=lambda x: x.trade_time):
        if t.direction == TradeDirection.BUY:
            buys[t.stock_code].append(t)
        elif t.direction == TradeDirection.SELL and buys.get(t.stock_code):
            buy_t = buys[t.stock_code].pop(0)
            yield buy_t, t


# ─── main entry ─────────────────────────────────────────────────────
def detect_patterns(
    trades: list[TradeRecord],
    market_data: list[MarketData],
) -> list[PatternResult]:
    price_map = _build_price_map(market_data)

    chase_high_ids: list[int] = []
    chase_high_impact: float = 0.0
    chase_high_examples: list[dict] = []

    early_profit_ids: list[int] = []
    early_profit_impact: float = 0.0
    early_profit_examples: list[dict] = []

    slow_stop_ids: list[int] = []
    slow_stop_impact: float = 0.0
    slow_stop_examples: list[dict] = []

    hold_too_long_ids: list[int] = []
    hold_too_long_impact: float = 0.0
    hold_too_long_examples: list[dict] = []

    for buy_t, sell_t in _pair_trades(trades):
        code = buy_t.stock_code
        plist = price_map.get(code, [])
        buy_date = buy_t.trade_time.date()
        sell_date = sell_t.trade_time.date()
        holding_days = (sell_t.trade_time - buy_t.trade_time).days

        pnl = sell_t.pnl or 0.0
        pnl_pct = sell_t.pnl_pct or 0.0

        # 1. chase_high — buy price > 5% above 5-day avg close
        avg5 = _get_avg_close(plist, buy_date, 5)
        if avg5 is not None and buy_t.price > avg5 * 1.05:
            trade_id = buy_t.id or 0
            chase_high_ids.append(trade_id)
            chase_high_impact += pnl
            chase_high_examples.append({
                "trade_id": trade_id,
                "stock": f"{buy_t.stock_code} {buy_t.stock_name}",
                "buy_date": buy_date.isoformat(),
                "sell_date": sell_date.isoformat(),
                "buy_price": buy_t.price,
                "sell_price": sell_t.price,
                "avg5": round(avg5, 2),
                "pnl": pnl,
            })

        # 2. early_profit — sell with 1%<pnl_pct<5% when stock rose >5% in next 5 days
        if 1 < pnl_pct < 5:
            future_close = _get_future_close(plist, sell_date, 5)
            if future_close is not None and future_close > sell_t.price * 1.05:
                trade_id = sell_t.id or 0
                missed = (future_close - sell_t.price) * sell_t.quantity
                early_profit_ids.append(trade_id)
                early_profit_impact += missed
                early_profit_examples.append({
                    "trade_id": trade_id,
                    "stock": f"{sell_t.stock_code} {sell_t.stock_name}",
                    "buy_date": buy_date.isoformat(),
                    "sell_date": sell_date.isoformat(),
                    "buy_price": buy_t.price,
                    "sell_price": sell_t.price,
                    "future_close": round(future_close, 2),
                    "missed_gain": round(missed, 2),
                })

        # 3. slow_stop_loss — sell with pnl_pct < -8%
        if pnl_pct < -8:
            trade_id = sell_t.id or 0
            slow_stop_ids.append(trade_id)
            slow_stop_impact += pnl
            slow_stop_examples.append({
                "trade_id": trade_id,
                "stock": f"{sell_t.stock_code} {sell_t.stock_name}",
                "buy_date": buy_date.isoformat(),
                "sell_date": sell_date.isoformat(),
                "buy_price": buy_t.price,
                "sell_price": sell_t.price,
                "pnl_pct": round(pnl_pct, 2),
                "pnl": round(pnl, 2),
                "holding_days": holding_days,
            })

        # 5. hold_too_long — holding > 20 trading days with negative pnl
        if holding_days > 20 and pnl < 0:
            trade_id = sell_t.id or 0
            hold_too_long_ids.append(trade_id)
            hold_too_long_impact += pnl
            hold_too_long_examples.append({
                "trade_id": trade_id,
                "stock": f"{sell_t.stock_code} {sell_t.stock_name}",
                "buy_date": buy_date.isoformat(),
                "sell_date": sell_date.isoformat(),
                "buy_price": buy_t.price,
                "sell_price": sell_t.price,
                "holding_days": holding_days,
                "pnl": round(pnl, 2),
            })

    # 4. over_trading — >5 trades per week for consecutive weeks
    trades_by_week: dict[str, int] = defaultdict(int)
    for t in trades:
        iso_year, iso_week, _ = t.trade_time.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        trades_by_week[key] += 1

    sorted_weeks = sorted(trades_by_week.keys())
    over_trading_weeks: list[str] = []
    consecutive = 0
    for wk in sorted_weeks:
        if trades_by_week[wk] > 5:
            consecutive += 1
            if consecutive >= 2:
                if wk not in over_trading_weeks:
                    over_trading_weeks.append(wk)
                # also add the prior one if not already
                idx = sorted_weeks.index(wk)
                prev_wk = sorted_weeks[idx - 1]
                if prev_wk not in over_trading_weeks:
                    over_trading_weeks.append(prev_wk)
        else:
            consecutive = 0

    over_trading_trade_ids = []
    if over_trading_weeks:
        for t in trades:
            iso_year, iso_week, _ = t.trade_time.isocalendar()
            key = f"{iso_year}-W{iso_week:02d}"
            if key in over_trading_weeks:
                over_trading_trade_ids.append(t.id or 0)

    # --- assemble results ---
    results: list[PatternResult] = []

    if chase_high_ids:
        chase_high_examples.sort(key=lambda x: abs(x.get("pnl", 0)), reverse=True)
        results.append(PatternResult(
            pattern_type=PatternType.CHASE_HIGH,
            pattern_name="追高买入",
            occurrences=len(chase_high_ids),
            affected_trades=chase_high_ids,
            total_impact=round(chase_high_impact, 2),
            description="买入价格高于近5日均价5%以上，存在追高风险",
            examples=chase_high_examples[:3],
        ))

    if early_profit_ids:
        early_profit_examples.sort(key=lambda x: abs(x.get("missed_gain", 0)), reverse=True)
        results.append(PatternResult(
            pattern_type=PatternType.EARLY_PROFIT_TAKE,
            pattern_name="止盈过早",
            occurrences=len(early_profit_ids),
            affected_trades=early_profit_ids,
            total_impact=round(early_profit_impact, 2),
            description="在盈利1%-5%时卖出，但此后股价继续上涨超5%",
            examples=early_profit_examples[:3],
        ))

    if slow_stop_ids:
        slow_stop_examples.sort(key=lambda x: abs(x.get("pnl", 0)), reverse=True)
        results.append(PatternResult(
            pattern_type=PatternType.SLOW_STOP_LOSS,
            pattern_name="止损过慢",
            occurrences=len(slow_stop_ids),
            affected_trades=slow_stop_ids,
            total_impact=round(slow_stop_impact, 2),
            description="卖出时亏损超过8%，未及时止损",
            examples=slow_stop_examples[:3],
        ))

    if over_trading_weeks:
        results.append(PatternResult(
            pattern_type=PatternType.OVER_TRADING,
            pattern_name="频繁交易",
            occurrences=len(over_trading_weeks),
            affected_trades=over_trading_trade_ids,
            total_impact=0.0,
            description=f"连续{len(over_trading_weeks)}周每周交易超过5次",
            examples=[{"weeks": over_trading_weeks[:5]}],
        ))

    if hold_too_long_ids:
        hold_too_long_examples.sort(key=lambda x: abs(x.get("pnl", 0)), reverse=True)
        results.append(PatternResult(
            pattern_type=PatternType.HOLD_TOO_LONG,
            pattern_name="持仓过久",
            occurrences=len(hold_too_long_ids),
            affected_trades=hold_too_long_ids,
            total_impact=round(hold_too_long_impact, 2),
            description="持仓超过20个交易日且仍为亏损状态",
            examples=hold_too_long_examples[:3],
        ))

    return results
