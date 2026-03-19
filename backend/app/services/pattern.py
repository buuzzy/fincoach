"""Pattern recognition engine — detects core trading anti-patterns."""

from __future__ import annotations

from app.models import (
    TradeRecord,
    MarketData,
    PatternType,
    PatternResult,
)
from app.core.constants import (
    FEE_DRAG_RATIO_THRESHOLD,
    buy_fee,
    sell_fee,
)
from app.utils.trade_utils import (
    pair_trades,
    build_price_map,
    get_avg_close,
    get_future_close,
)


# ─── main entry ─────────────────────────────────────────────────────
def detect_patterns(
    trades: list[TradeRecord],
    market_data: list[MarketData],
) -> list[PatternResult]:
    price_map = build_price_map(market_data)

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

    # fee_drag 中间数据
    total_estimated_fee: float = 0.0   # 所有已平仓交易的估算手续费合计
    total_gross_profit: float = 0.0    # 所有盈利笔的毛利润合计
    fee_drag_ids: list[int] = []
    fee_drag_examples: list[dict] = []

    for buy_t, sell_t in pair_trades(trades):
        code = buy_t.stock_code
        plist = price_map.get(code, [])
        buy_date = buy_t.trade_time.date()
        sell_date = sell_t.trade_time.date()
        holding_days = (sell_t.trade_time - buy_t.trade_time).days

        pnl = sell_t.pnl or 0.0
        pnl_pct = sell_t.pnl_pct or 0.0

        buy_trade_id = buy_t.id or 0
        sell_trade_id = sell_t.id or 0

        # 1. chase_high — buy price > 5% above 5-day avg close
        avg5 = get_avg_close(plist, buy_date, 5)
        if avg5 is not None and buy_t.price > avg5 * 1.05:
            chase_high_ids.append(buy_trade_id)
            chase_high_impact += pnl
            chase_high_examples.append({
                "trade_id": buy_trade_id,
                "buy_trade_id": buy_trade_id,
                "sell_trade_id": sell_trade_id,
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
            future_close = get_future_close(plist, sell_date, 5)
            if future_close is not None and future_close > sell_t.price * 1.05:
                missed = (future_close - sell_t.price) * sell_t.quantity
                early_profit_ids.append(sell_trade_id)
                early_profit_impact += missed
                early_profit_examples.append({
                    "trade_id": sell_trade_id,
                    "buy_trade_id": buy_trade_id,
                    "sell_trade_id": sell_trade_id,
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
            slow_stop_ids.append(sell_trade_id)
            slow_stop_impact += pnl
            slow_stop_examples.append({
                "trade_id": sell_trade_id,
                "buy_trade_id": buy_trade_id,
                "sell_trade_id": sell_trade_id,
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
            hold_too_long_ids.append(sell_trade_id)
            hold_too_long_impact += pnl
            hold_too_long_examples.append({
                "trade_id": sell_trade_id,
                "buy_trade_id": buy_trade_id,
                "sell_trade_id": sell_trade_id,
                "stock": f"{sell_t.stock_code} {sell_t.stock_name}",
                "buy_date": buy_date.isoformat(),
                "sell_date": sell_date.isoformat(),
                "buy_price": buy_t.price,
                "sell_price": sell_t.price,
                "holding_days": holding_days,
                "pnl": round(pnl, 2),
            })

        # 6. fee_drag — 累计手续费侵蚀统计（已平仓交易）
        buy_amount = buy_t.price * buy_t.quantity
        sell_amount = sell_t.price * sell_t.quantity
        round_trip_fee = buy_fee(buy_amount) + sell_fee(sell_amount)
        total_estimated_fee += round_trip_fee
        if pnl > 0:
            total_gross_profit += pnl

    # ── fee_drag：整体手续费侵蚀率超标时，找出「低效短线」交易 ───────
    fee_drag_ratio = (
        total_estimated_fee / total_gross_profit
        if total_gross_profit > 0 else 0.0
    )

    if fee_drag_ratio > FEE_DRAG_RATIO_THRESHOLD:
        for buy_t, sell_t in pair_trades(trades):
            pnl = sell_t.pnl or 0.0
            holding_days = (sell_t.trade_time - buy_t.trade_time).days
            buy_amount = buy_t.price * buy_t.quantity
            sell_amount = sell_t.price * sell_t.quantity
            round_trip_fee = buy_fee(buy_amount) + sell_fee(sell_amount)

            if holding_days < 5 and abs(pnl) < round_trip_fee * 2:
                b_id = buy_t.id or 0
                s_id = sell_t.id or 0
                fee_drag_ids.append(s_id)
                fee_drag_examples.append({
                    "trade_id": s_id,
                    "buy_trade_id": b_id,
                    "sell_trade_id": s_id,
                    "stock": f"{sell_t.stock_code} {sell_t.stock_name}",
                    "buy_date": buy_t.trade_time.date().isoformat(),
                    "sell_date": sell_t.trade_time.date().isoformat(),
                    "buy_price": buy_t.price,
                    "sell_price": sell_t.price,
                    "holding_days": holding_days,
                    "pnl": round(pnl, 2),
                    "estimated_fee": round(round_trip_fee, 2),
                })

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

    if fee_drag_ids:
        fee_drag_examples.sort(key=lambda x: abs(x.get("pnl", 0)))
        results.append(PatternResult(
            pattern_type=PatternType.FEE_DRAG,
            pattern_name="手续费侵蚀",
            occurrences=len(fee_drag_ids),
            affected_trades=fee_drag_ids,
            total_impact=round(-total_estimated_fee, 2),  # 负值：手续费是成本
            description=(
                f"估算手续费合计 {total_estimated_fee:,.0f} 元，"
                f"占毛利润的 {fee_drag_ratio * 100:.1f}%，"
                f"其中 {len(fee_drag_ids)} 笔短线交易盈亏未能覆盖交易成本"
            ),
            examples=fee_drag_examples[:3],
        ))

    return results
