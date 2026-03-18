"""Backtest engine — simulates alternative strategies on historical trades."""

from __future__ import annotations

from collections import defaultdict

from app.models import (
    TradeRecord,
    MarketData,
    PatternResult,
    PatternType,
    TradeDirection,
    BacktestScenario,
    BacktestResult,
)


def _build_price_map(
    market_data: list[MarketData],
) -> dict[str, list[MarketData]]:
    by_stock: dict[str, list[MarketData]] = defaultdict(list)
    for md in market_data:
        by_stock[md.stock_code].append(md)
    for code in by_stock:
        by_stock[code].sort(key=lambda m: m.trade_date)
    return by_stock


def _get_future_close(
    price_list: list[MarketData],
    target_date,
    days_ahead: int,
) -> float | None:
    future = [m for m in price_list if m.trade_date > target_date]
    if len(future) < days_ahead:
        return None
    return future[days_ahead - 1].close_price


def _pair_trades(trades: list[TradeRecord]):
    buys: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in sorted(trades, key=lambda x: x.trade_time):
        if t.direction == TradeDirection.BUY:
            buys[t.stock_code].append(t)
        elif t.direction == TradeDirection.SELL and buys.get(t.stock_code):
            buy_t = buys[t.stock_code].pop(0)
            yield buy_t, t


def run_backtest(
    trades: list[TradeRecord],
    market_data: list[MarketData],
    patterns: list[PatternResult],
) -> BacktestResult:
    price_map = _build_price_map(market_data)

    pattern_map: dict[str, PatternResult] = {
        p.pattern_type.value: p for p in patterns
    }

    slow_stop_ids = set(
        pattern_map[PatternType.SLOW_STOP_LOSS.value].affected_trades
    ) if PatternType.SLOW_STOP_LOSS.value in pattern_map else set()

    early_profit_ids = set(
        pattern_map[PatternType.EARLY_PROFIT_TAKE.value].affected_trades
    ) if PatternType.EARLY_PROFIT_TAKE.value in pattern_map else set()

    chase_high_ids = set(
        pattern_map[PatternType.CHASE_HIGH.value].affected_trades
    ) if PatternType.CHASE_HIGH.value in pattern_map else set()

    # Collect all trade pairs once
    all_pairs = list(_pair_trades(trades))

    # ── Scenario 1: 止损线下调2% — sell at -6% instead of actual ───
    s1_original = 0.0
    s1_adjusted = 0.0
    s1_details: list[dict] = []

    for buy_t, sell_t in all_pairs:
        pnl = sell_t.pnl or 0.0
        buy_date = buy_t.trade_time.date().isoformat()
        sell_date = sell_t.trade_time.date().isoformat()

        if (sell_t.id or 0) in slow_stop_ids:
            # simulate selling at -6% loss instead of actual (< -8%)
            simulated_pnl = -0.06 * buy_t.price * buy_t.quantity
        else:
            simulated_pnl = pnl

        s1_original += pnl
        s1_adjusted += simulated_pnl
        s1_details.append({
            "trade_id": sell_t.id,
            "stock": f"{sell_t.stock_code} {sell_t.stock_name}",
            "buy_date": buy_date,
            "sell_date": sell_date,
            "buy_price": buy_t.price,
            "sell_price": sell_t.price,
            "original_pnl": round(pnl, 2),
            "adjusted_pnl": round(simulated_pnl, 2),
        })

    s1_details.sort(key=lambda x: x["sell_date"])

    # ── Scenario 2: 止盈线上调5% — hold 5 more days ────────────────
    s2_original = 0.0
    s2_adjusted = 0.0
    s2_details: list[dict] = []

    for buy_t, sell_t in all_pairs:
        pnl = sell_t.pnl or 0.0
        buy_date = buy_t.trade_time.date().isoformat()
        sell_date_obj = sell_t.trade_time.date()
        sell_date = sell_date_obj.isoformat()

        if (sell_t.id or 0) in early_profit_ids:
            plist = price_map.get(sell_t.stock_code, [])
            future_close = _get_future_close(plist, sell_date_obj, 5)
            if future_close is not None:
                simulated_pnl = (future_close - buy_t.price) * buy_t.quantity
            else:
                simulated_pnl = pnl  # no data, keep original
        else:
            simulated_pnl = pnl

        s2_original += pnl
        s2_adjusted += simulated_pnl
        s2_details.append({
            "trade_id": sell_t.id,
            "stock": f"{sell_t.stock_code} {sell_t.stock_name}",
            "buy_date": buy_date,
            "sell_date": sell_date,
            "buy_price": buy_t.price,
            "sell_price": sell_t.price,
            "original_pnl": round(pnl, 2),
            "adjusted_pnl": round(simulated_pnl, 2),
        })

    s2_details.sort(key=lambda x: x["sell_date"])

    # ── Scenario 3: 减少追高 — remove chase-high trades entirely ───
    s3_original = 0.0
    s3_adjusted = 0.0
    s3_details: list[dict] = []

    for buy_t, sell_t in all_pairs:
        pnl = sell_t.pnl or 0.0
        buy_date = buy_t.trade_time.date().isoformat()
        sell_date = sell_t.trade_time.date().isoformat()

        if (buy_t.id or 0) in chase_high_ids:
            simulated_pnl = 0.0
        else:
            simulated_pnl = pnl

        s3_original += pnl
        s3_adjusted += simulated_pnl
        s3_details.append({
            "trade_id": buy_t.id,
            "stock": f"{buy_t.stock_code} {buy_t.stock_name}",
            "buy_date": buy_date,
            "sell_date": sell_date,
            "buy_price": buy_t.price,
            "sell_price": sell_t.price,
            "original_pnl": round(pnl, 2),
            "adjusted_pnl": round(simulated_pnl, 2),
        })

    s3_details.sort(key=lambda x: x["sell_date"])

    # ── Build scenarios ─────────────────────────────────────────────
    scenarios: list[BacktestScenario] = []

    def _make_scenario(
        name: str,
        description: str,
        param_change: str,
        original: float,
        adjusted: float,
        details: list[dict],
    ) -> BacktestScenario:
        improvement = adjusted - original
        improvement_pct = (improvement / abs(original) * 100) if original != 0 else 0.0
        return BacktestScenario(
            name=name,
            description=description,
            param_change=param_change,
            original_pnl=round(original, 2),
            adjusted_pnl=round(adjusted, 2),
            improvement=round(improvement, 2),
            improvement_pct=round(improvement_pct, 2),
            trade_details=details,
        )

    scenarios.append(_make_scenario(
        name="止损线下调2%",
        description="将止损线从-8%调整为-6%，提前止损减少单笔损失",
        param_change="止损线: -8% → -6%",
        original=s1_original,
        adjusted=s1_adjusted,
        details=s1_details,
    ))

    scenarios.append(_make_scenario(
        name="止盈线上调5%",
        description="对止盈过早的交易，模拟多持有5个交易日后卖出",
        param_change="持有时间: +5个交易日",
        original=s2_original,
        adjusted=s2_adjusted,
        details=s2_details,
    ))

    scenarios.append(_make_scenario(
        name="减少追高",
        description="移除追高买入的交易，避免高位接盘",
        param_change="移除追高交易",
        original=s3_original,
        adjusted=s3_adjusted,
        details=s3_details,
    ))

    # Best scenario = largest improvement
    best = max(scenarios, key=lambda s: s.improvement)

    return BacktestResult(
        scenarios=scenarios,
        best_scenario=best.name,
        max_improvement=best.improvement,
    )
