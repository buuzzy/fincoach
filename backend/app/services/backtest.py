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


def _get_ma5(price_list: list[MarketData], before_date) -> float | None:
    """5-day moving average of close price strictly before before_date."""
    prior = [m for m in price_list if m.trade_date < before_date]
    if len(prior) < 5:
        return None
    return sum(m.close_price for m in prior[-5:]) / 5


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

    # Collect all trade pairs once
    all_pairs = list(_pair_trades(trades))

    # ── Scenario 1: 止损线下调2% ────────────────────────────────────
    # Rule: for any trade where actual loss > 6%, simulate stopping at -6%.
    # This is a direct calculation — no pattern ID matching needed.
    s1_original = 0.0
    s1_adjusted = 0.0
    s1_details: list[dict] = []

    for buy_t, sell_t in all_pairs:
        pnl = sell_t.pnl or 0.0
        qty = buy_t.quantity or 0
        buy_price = buy_t.price or 0.0
        buy_date = buy_t.trade_time.date().isoformat()
        sell_date = sell_t.trade_time.date().isoformat()

        pnl_pct = (sell_t.price - buy_price) / buy_price * 100 if buy_price else 0.0

        if pnl_pct < -6.0:
            # Stop out at -6% instead of the actual deeper loss
            simulated_pnl = -0.06 * buy_price * qty
        else:
            simulated_pnl = pnl

        s1_original += pnl
        s1_adjusted += simulated_pnl
        s1_details.append({
            "trade_id": sell_t.id,
            "stock": f"{sell_t.stock_code} {sell_t.stock_name}",
            "buy_date": buy_date,
            "sell_date": sell_date,
            "buy_price": buy_price,
            "sell_price": sell_t.price,
            "original_pnl": round(pnl, 2),
            "adjusted_pnl": round(simulated_pnl, 2),
        })

    s1_details.sort(key=lambda x: x["sell_date"])

    # ── Scenario 2: 止盈线上调5% ─────────────────────────────────────
    # Rule: for profitable trades that gained between 1% and 20%,
    # check if holding 5 more trading days would have yielded a higher price.
    # If yes, use the future price; if no future data or price dropped, keep actual.
    s2_original = 0.0
    s2_adjusted = 0.0
    s2_details: list[dict] = []

    for buy_t, sell_t in all_pairs:
        pnl = sell_t.pnl or 0.0
        qty = buy_t.quantity or 0
        buy_price = buy_t.price or 0.0
        sell_price = sell_t.price or 0.0
        buy_date = buy_t.trade_time.date().isoformat()
        sell_date_obj = sell_t.trade_time.date()
        sell_date = sell_date_obj.isoformat()

        pnl_pct = (sell_price - buy_price) / buy_price * 100 if buy_price else 0.0

        # Only apply to trades with modest gains (1%–20%): these are candidates
        # where early profit-taking might have left money on the table.
        if 1.0 < pnl_pct < 20.0:
            plist = price_map.get(sell_t.stock_code, [])
            future_close = _get_future_close(plist, sell_date_obj, 5)
            if future_close is not None and future_close > sell_price:
                # Holding 5 more days would have been better — simulate it
                simulated_pnl = (future_close - buy_price) * qty
            else:
                simulated_pnl = pnl  # no improvement or no data
        else:
            simulated_pnl = pnl

        s2_original += pnl
        s2_adjusted += simulated_pnl
        s2_details.append({
            "trade_id": sell_t.id,
            "stock": f"{sell_t.stock_code} {sell_t.stock_name}",
            "buy_date": buy_date,
            "sell_date": sell_date,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "original_pnl": round(pnl, 2),
            "adjusted_pnl": round(simulated_pnl, 2),
        })

    s2_details.sort(key=lambda x: x["sell_date"])

    # ── Scenario 3: 减少追高 ─────────────────────────────────────────
    # Rule: identify chase-high buys directly (buy price > MA5 * 1.03)
    # Only avoid trades that were BOTH chase-high AND unprofitable.
    # Profitable chase-high trades are kept — they were lucky but still made money.
    s3_original = 0.0
    s3_adjusted = 0.0
    s3_details: list[dict] = []

    for buy_t, sell_t in all_pairs:
        pnl = sell_t.pnl or 0.0
        buy_price = buy_t.price or 0.0
        buy_date = buy_t.trade_time.date().isoformat()
        sell_date = sell_t.trade_time.date().isoformat()

        plist = price_map.get(buy_t.stock_code, [])
        ma5 = _get_ma5(plist, buy_t.trade_time.date())

        is_chase_high = (ma5 is not None) and (buy_price > ma5 * 1.03)

        if is_chase_high and pnl < 0:
            # Avoided a bad chase-high trade — gain is the avoided loss
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
            "buy_price": buy_price,
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
        description="对小幅盈利的交易，模拟多持有5个交易日后卖出",
        param_change="持有时间: +5个交易日",
        original=s2_original,
        adjusted=s2_adjusted,
        details=s2_details,
    ))

    scenarios.append(_make_scenario(
        name="减少追高",
        description="规避在5日均线3%以上追高买入且亏损的交易",
        param_change="移除追高亏损交易",
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
