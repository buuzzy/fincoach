"""Backtest engine — runs LLM-designed scenarios on historical trades.

Supported scenario types:
  stop_loss_tighten     params: threshold_pct (e.g. -5)
  profit_hold_extend    params: hold_days (e.g. 10)
  chase_high_avoid      params: ma_multiplier (e.g. 1.03)
  trade_frequency_limit params: max_per_week (e.g. 3)
  hold_duration_limit   params: max_days (e.g. 15)
  fee_drag_reduce       params: max_holding_days (e.g. 5), fee_cover_multiplier (e.g. 2.0)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from app.models import (
    TradeRecord,
    MarketData,
    TradeDirection,
    BacktestScenario,
    BacktestScenarioConfig,
    BacktestResult,
)

# A股手续费常数（与 pattern.py 保持一致）
_COMMISSION_RATE = 0.0003   # 佣金 0.03%（买卖双向）
_STAMP_DUTY_RATE  = 0.001   # 印花税 0.10%（仅卖出）

def _buy_fee(amount: float) -> float:
    return amount * _COMMISSION_RATE

def _sell_fee(amount: float) -> float:
    return amount * (_COMMISSION_RATE + _STAMP_DUTY_RATE)


# ── Market data helpers ──────────────────────────────────────────────────────

def _build_price_map(market_data: list[MarketData]) -> dict[str, list[MarketData]]:
    by_stock: dict[str, list[MarketData]] = defaultdict(list)
    for md in market_data:
        by_stock[md.stock_code].append(md)
    for code in by_stock:
        by_stock[code].sort(key=lambda m: m.trade_date)
    return by_stock


def _get_future_close(price_list: list[MarketData], target_date, days_ahead: int) -> float | None:
    future = [m for m in price_list if m.trade_date > target_date]
    if len(future) < days_ahead:
        return None
    return future[days_ahead - 1].close_price


def _get_ma(price_list: list[MarketData], before_date, window: int = 5) -> float | None:
    prior = [m for m in price_list if m.trade_date < before_date]
    if len(prior) < window:
        return None
    return sum(m.close_price for m in prior[-window:]) / window


# ── Trade pairing ────────────────────────────────────────────────────────────

def _pair_trades(trades: list[TradeRecord]):
    buys: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in sorted(trades, key=lambda x: x.trade_time):
        if t.direction == TradeDirection.BUY:
            buys[t.stock_code].append(t)
        elif t.direction == TradeDirection.SELL and buys.get(t.stock_code):
            yield buys[t.stock_code].pop(0), t


# ── Scenario simulators ──────────────────────────────────────────────────────

def _run_stop_loss_tighten(
    pairs: list[tuple[TradeRecord, TradeRecord]],
    price_map: dict[str, list[MarketData]],
    threshold_pct: float,  # e.g. -5.0  means stop at -5%
) -> tuple[float, float, list[dict]]:
    orig_total = adj_total = 0.0
    details: list[dict] = []
    for buy_t, sell_t in pairs:
        pnl = sell_t.pnl or 0.0
        buy_price = buy_t.price or 0.0
        qty = buy_t.quantity or 0
        pnl_pct = (sell_t.price - buy_price) / buy_price * 100 if buy_price else 0.0

        if pnl_pct < threshold_pct:
            # Simulate stopping out at threshold_pct
            sim_pnl = (threshold_pct / 100) * buy_price * qty
        else:
            sim_pnl = pnl

        orig_total += pnl
        adj_total += sim_pnl
        details.append(_detail(buy_t, sell_t, pnl, sim_pnl))
    return orig_total, adj_total, details


def _run_profit_hold_extend(
    pairs: list[tuple[TradeRecord, TradeRecord]],
    price_map: dict[str, list[MarketData]],
    hold_days: int,  # extra trading days to hold
) -> tuple[float, float, list[dict]]:
    orig_total = adj_total = 0.0
    details: list[dict] = []
    for buy_t, sell_t in pairs:
        pnl = sell_t.pnl or 0.0
        buy_price = buy_t.price or 0.0
        qty = buy_t.quantity or 0
        sell_price = sell_t.price or 0.0
        pnl_pct = (sell_price - buy_price) / buy_price * 100 if buy_price else 0.0

        sim_pnl = pnl
        # Only apply to profitable exits — these are potential early-profit-take candidates
        if pnl_pct > 0:
            plist = price_map.get(sell_t.stock_code, [])
            future_close = _get_future_close(plist, sell_t.trade_time.date(), hold_days)
            if future_close is not None and future_close > sell_price:
                sim_pnl = (future_close - buy_price) * qty

        orig_total += pnl
        adj_total += sim_pnl
        details.append(_detail(buy_t, sell_t, pnl, sim_pnl))
    return orig_total, adj_total, details


def _run_chase_high_avoid(
    pairs: list[tuple[TradeRecord, TradeRecord]],
    price_map: dict[str, list[MarketData]],
    ma_multiplier: float,  # e.g. 1.03 means buy > MA5 * 1.03
) -> tuple[float, float, list[dict]]:
    orig_total = adj_total = 0.0
    details: list[dict] = []
    for buy_t, sell_t in pairs:
        pnl = sell_t.pnl or 0.0
        buy_price = buy_t.price or 0.0

        plist = price_map.get(buy_t.stock_code, [])
        ma5 = _get_ma(plist, buy_t.trade_time.date(), 5)
        is_chase = ma5 is not None and buy_price > ma5 * ma_multiplier

        # Only avoid if it was both a chase AND a losing trade
        if is_chase and pnl < 0:
            sim_pnl = 0.0
        else:
            sim_pnl = pnl

        orig_total += pnl
        adj_total += sim_pnl
        details.append(_detail(buy_t, sell_t, pnl, sim_pnl))
    return orig_total, adj_total, details


def _run_trade_frequency_limit(
    pairs: list[tuple[TradeRecord, TradeRecord]],
    price_map: dict[str, list[MarketData]],
    max_per_week: int,  # e.g. 3
) -> tuple[float, float, list[dict]]:
    """Simulate keeping only the first max_per_week trades per week.

    Excess trades in a week are assumed not executed (pnl = 0).
    We count by buy date (one buy+sell pair = one trade).
    """
    week_counts: dict[str, int] = defaultdict(int)
    orig_total = adj_total = 0.0
    details: list[dict] = []

    for buy_t, sell_t in sorted(pairs, key=lambda p: p[0].trade_time):
        pnl = sell_t.pnl or 0.0
        buy_date = buy_t.trade_time.date()
        iso_year, iso_week, _ = buy_date.isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"

        week_counts[week_key] += 1
        if week_counts[week_key] > max_per_week:
            sim_pnl = 0.0  # trade not executed under the limit
        else:
            sim_pnl = pnl

        orig_total += pnl
        adj_total += sim_pnl
        details.append(_detail(buy_t, sell_t, pnl, sim_pnl))

    details.sort(key=lambda x: x["sell_date"])
    return orig_total, adj_total, details


def _run_hold_duration_limit(
    pairs: list[tuple[TradeRecord, TradeRecord]],
    price_map: dict[str, list[MarketData]],
    max_days: int,
) -> tuple[float, float, list[dict]]:
    """Simulate force-selling losing positions at close on day max_days."""
    orig_total = adj_total = 0.0
    details: list[dict] = []

    for buy_t, sell_t in pairs:
        pnl = sell_t.pnl or 0.0
        buy_price = buy_t.price or 0.0
        qty = buy_t.quantity or 0
        holding_days = (sell_t.trade_time - buy_t.trade_time).days

        sim_pnl = pnl
        if pnl < 0 and holding_days > max_days:
            plist = price_map.get(buy_t.stock_code, [])
            forced_date = buy_t.trade_time.date() + timedelta(days=max_days)
            candidates = [m for m in plist if m.trade_date >= forced_date]
            if candidates:
                forced_close = candidates[0].close_price
                sim_pnl = (forced_close - buy_price) * qty

        orig_total += pnl
        adj_total += sim_pnl
        details.append(_detail(buy_t, sell_t, pnl, sim_pnl))

    return orig_total, adj_total, details


def _run_fee_drag_reduce(
    pairs: list[tuple[TradeRecord, TradeRecord]],
    price_map: dict[str, list[MarketData]],
    max_holding_days: int = 5,
    fee_cover_multiplier: float = 2.0,
) -> tuple[float, float, list[dict]]:
    """Simulate avoiding trades where |pnl| < estimated round-trip fee × multiplier
    AND holding period < max_holding_days.

    These are 'inefficient short-term trades' where transaction costs erode returns.
    Improvement = avoided losses + saved fees on near-zero-profit trades.
    """
    orig_total = adj_total = 0.0
    details: list[dict] = []

    for buy_t, sell_t in pairs:
        pnl = sell_t.pnl or 0.0
        buy_price = buy_t.price or 0.0
        qty = buy_t.quantity or 0
        holding_days = (sell_t.trade_time - buy_t.trade_time).days

        buy_amount = buy_price * qty
        sell_amount = (sell_t.price or 0.0) * qty
        round_trip_fee = _buy_fee(buy_amount) + _sell_fee(sell_amount)

        # Skip if this trade didn't cover its own costs AND was short-term
        if holding_days < max_holding_days and abs(pnl) < round_trip_fee * fee_cover_multiplier:
            sim_pnl = 0.0  # trade not executed — avoid the loss and save the fee
        else:
            sim_pnl = pnl

        orig_total += pnl
        adj_total += sim_pnl
        details.append(_detail(buy_t, sell_t, pnl, sim_pnl))

    return orig_total, adj_total, details


# ── Detail builder ───────────────────────────────────────────────────────────

def _detail(buy_t: TradeRecord, sell_t: TradeRecord, orig_pnl: float, adj_pnl: float) -> dict:
    return {
        "trade_id": sell_t.id,
        "stock": f"{sell_t.stock_code} {sell_t.stock_name}",
        "buy_date": buy_t.trade_time.date().isoformat(),
        "sell_date": sell_t.trade_time.date().isoformat(),
        "buy_price": buy_t.price,
        "sell_price": sell_t.price,
        "original_pnl": round(orig_pnl, 2),
        "adjusted_pnl": round(adj_pnl, 2),
    }


# ── Dispatcher ───────────────────────────────────────────────────────────────

_SCENARIO_FN = {
    "stop_loss_tighten":     _run_stop_loss_tighten,
    "profit_hold_extend":    _run_profit_hold_extend,
    "chase_high_avoid":      _run_chase_high_avoid,
    "trade_frequency_limit": _run_trade_frequency_limit,
    "hold_duration_limit":   _run_hold_duration_limit,
    "fee_drag_reduce":       _run_fee_drag_reduce,
}

_DEFAULT_PARAMS = {
    "stop_loss_tighten":     {"threshold_pct": -6.0},
    "profit_hold_extend":    {"hold_days": 5},
    "chase_high_avoid":      {"ma_multiplier": 1.03},
    "trade_frequency_limit": {"max_per_week": 3},
    "hold_duration_limit":   {"max_days": 15},
    "fee_drag_reduce":       {"max_holding_days": 5, "fee_cover_multiplier": 2.0},
}

_DEFAULT_DESCRIPTIONS = {
    "stop_loss_tighten":     "提前止损，减少单笔深度亏损",
    "profit_hold_extend":    "延长持盈时间，减少过早离场",
    "chase_high_avoid":      "规避追高亏损交易",
    "trade_frequency_limit": "控制每周交易频率",
    "hold_duration_limit":   "限制亏损仓位持仓时长",
    "fee_drag_reduce":       "规避盈亏未能覆盖手续费的低效短线交易",
}


def _param_change_str(stype: str, params: dict) -> str:
    if stype == "stop_loss_tighten":
        return f"止损线: {params.get('threshold_pct', -6)}%"
    if stype == "profit_hold_extend":
        return f"延长持有: +{params.get('hold_days', 5)}个交易日"
    if stype == "chase_high_avoid":
        return f"追高阈值: MA5 × {params.get('ma_multiplier', 1.03)}"
    if stype == "trade_frequency_limit":
        return f"每周最多: {params.get('max_per_week', 3)}次"
    if stype == "hold_duration_limit":
        return f"最长持仓: {params.get('max_days', 15)}天"
    if stype == "fee_drag_reduce":
        return f"短线阈值: 持仓 < {params.get('max_holding_days', 5)}天且未覆盖手续费"
    return ""


# ── Public entry point ───────────────────────────────────────────────────────

def run_backtest(
    trades: list[TradeRecord],
    market_data: list[MarketData],
    scenario_configs: list[BacktestScenarioConfig] | None = None,
) -> BacktestResult:
    """Run backtest with LLM-designed scenario configs.

    Falls back to three sensible default scenarios when scenario_configs is None
    (e.g. if the LLM call failed).
    """
    price_map = _build_price_map(market_data)
    all_pairs = list(_pair_trades(trades))

    # Default fallback scenarios
    if not scenario_configs:
        scenario_configs = [
            BacktestScenarioConfig(
                type="stop_loss_tighten",
                name="收紧止损至-6%",
                llm_rationale="",
                params={"threshold_pct": -6.0},
            ),
            BacktestScenarioConfig(
                type="profit_hold_extend",
                name="延长持盈5日",
                llm_rationale="",
                params={"hold_days": 5},
            ),
            BacktestScenarioConfig(
                type="chase_high_avoid",
                name="减少追高",
                llm_rationale="",
                params={"ma_multiplier": 1.03},
            ),
        ]

    scenarios: list[BacktestScenario] = []

    for cfg in scenario_configs:
        fn = _SCENARIO_FN.get(cfg.type)
        if fn is None:
            continue

        params = {**_DEFAULT_PARAMS.get(cfg.type, {}), **cfg.params}
        orig, adj, details = fn(all_pairs, price_map, **params)
        details.sort(key=lambda x: x["sell_date"])

        improvement = adj - orig
        improvement_pct = (improvement / abs(orig) * 100) if orig != 0 else 0.0

        scenarios.append(BacktestScenario(
            name=cfg.name,
            description=cfg.llm_rationale or _DEFAULT_DESCRIPTIONS.get(cfg.type, ""),
            param_change=_param_change_str(cfg.type, params),
            original_pnl=round(orig, 2),
            adjusted_pnl=round(adj, 2),
            improvement=round(improvement, 2),
            improvement_pct=round(improvement_pct, 2),
            trade_details=details,
            ai_interpretation="",  # filled in by ai_agent after LLM Call 2
        ))

    if not scenarios:
        # edge case: all types unknown
        return BacktestResult(scenarios=[], best_scenario="", max_improvement=0.0)

    best = max(scenarios, key=lambda s: s.improvement)
    return BacktestResult(
        scenarios=scenarios,
        best_scenario=best.name,
        max_improvement=best.improvement,
    )
