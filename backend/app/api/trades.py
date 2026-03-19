"""Trades API — list closed positions and generate single-trade reviews."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db, get_async_session
from app.models import TradeORM, StockNewsORM, MarketDataORM, UserORM

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trades", tags=["trades"])


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class ClosedTrade(BaseModel):
    """A matched buy+sell pair — one closed position."""
    buy_trade_id: int
    sell_trade_id: int
    stock_code: str
    stock_name: str
    buy_time: datetime
    sell_time: datetime
    buy_price: float
    sell_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    hold_days: int


class TradeReviewStatus(str):
    GENERATING = "generating"
    COMPLETED  = "completed"
    FAILED     = "failed"


class TradeReviewResponse(BaseModel):
    buy_trade_id: int
    sell_trade_id: int
    stock_code: str
    stock_name: str
    buy_time: datetime
    sell_time: datetime
    buy_price: float
    sell_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    hold_days: int
    # K-line during holding period
    kline: list[dict] = []
    # News during holding period (from stock_news table)
    news: list[dict] = []
    # AI review
    status: str = TradeReviewStatus.GENERATING
    ai_review: Optional[str] = None
    error_message: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pair_trades(trades: list[TradeORM]) -> list[tuple[TradeORM, TradeORM]]:
    """Match buy→sell pairs for the same stock in chronological order."""
    from collections import deque
    buy_queues: dict[str, deque] = {}
    pairs: list[tuple[TradeORM, TradeORM]] = []

    for t in sorted(trades, key=lambda x: x.trade_time):
        code = t.stock_code
        if t.direction.value == "buy":
            buy_queues.setdefault(code, deque()).append(t)
        elif t.direction.value == "sell":
            q = buy_queues.get(code)
            if q:
                buy_trade = q.popleft()
                pairs.append((buy_trade, t))

    return pairs


def _hold_days(buy_time: datetime, sell_time: datetime) -> int:
    return max(1, (sell_time.date() - buy_time.date()).days)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/{user_id}/closed", response_model=list[ClosedTrade])
async def list_closed_trades(
    user_id: int,
    start: str,   # YYYY-MM-DD
    end: str,     # YYYY-MM-DD
    db: AsyncSession = Depends(get_db),
):
    """Return all closed (buy+sell matched) positions in the given date range."""
    user = await db.get(UserORM, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        period_start = date.fromisoformat(start)
        period_end   = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")

    stmt = (
        select(TradeORM)
        .where(
            TradeORM.user_id == user_id,
            cast(TradeORM.trade_time, Date) >= period_start,
            cast(TradeORM.trade_time, Date) <= period_end,
        )
        .order_by(TradeORM.trade_time)
    )
    result = await db.execute(stmt)
    trades = result.scalars().all()

    pairs = _pair_trades(list(trades))

    closed: list[ClosedTrade] = []
    for buy_t, sell_t in pairs:
        pnl     = sell_t.pnl or 0.0
        pnl_pct = sell_t.pnl_pct or 0.0
        closed.append(ClosedTrade(
            buy_trade_id  = buy_t.id,
            sell_trade_id = sell_t.id,
            stock_code    = buy_t.stock_code,
            stock_name    = buy_t.stock_name,
            buy_time      = buy_t.trade_time,
            sell_time     = sell_t.trade_time,
            buy_price     = buy_t.price,
            sell_price    = sell_t.price,
            quantity      = buy_t.quantity,
            pnl           = pnl,
            pnl_pct       = pnl_pct,
            hold_days     = _hold_days(buy_t.trade_time, sell_t.trade_time),
        ))

    # Sort by sell_time desc (most recent first)
    closed.sort(key=lambda x: x.sell_time, reverse=True)
    return closed


@router.get("/review/{buy_trade_id}/{sell_trade_id}", response_model=TradeReviewResponse)
async def get_trade_review(
    buy_trade_id: int,
    sell_trade_id: int,
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Return K-line, news, and AI review for a single closed position."""
    buy_t  = await db.get(TradeORM, buy_trade_id)
    sell_t = await db.get(TradeORM, sell_trade_id)

    if not buy_t or not sell_t:
        raise HTTPException(status_code=404, detail="交易记录不存在")
    if buy_t.user_id != sell_t.user_id:
        raise HTTPException(status_code=400, detail="买卖交易用户不匹配")

    buy_date  = buy_t.trade_time.date()
    sell_date = sell_t.trade_time.date()
    code      = buy_t.stock_code
    name      = buy_t.stock_name
    pnl       = sell_t.pnl or 0.0
    pnl_pct   = sell_t.pnl_pct or 0.0
    hold_days = _hold_days(buy_t.trade_time, sell_t.trade_time)

    # ── K-line from market_data ────────────────────────────────────────────────
    stmt_kline = (
        select(MarketDataORM)
        .where(
            MarketDataORM.stock_code == code,
            MarketDataORM.trade_date >= buy_date,
            MarketDataORM.trade_date <= sell_date,
        )
        .order_by(MarketDataORM.trade_date)
    )
    kline_res = await db.execute(stmt_kline)
    kline_orms = kline_res.scalars().all()
    kline = [
        {
            "date":       str(k.trade_date),
            "open":       k.open_price,
            "high":       k.high_price,
            "low":        k.low_price,
            "close":      k.close_price,
            "volume":     k.volume,
            "change_pct": k.change_pct,
        }
        for k in kline_orms
    ]

    # ── News from stock_news ───────────────────────────────────────────────────
    stmt_news = (
        select(StockNewsORM)
        .where(
            StockNewsORM.stock_code == code,
            StockNewsORM.publish_time >= datetime.combine(buy_date, datetime.min.time()),
            StockNewsORM.publish_time <= datetime.combine(sell_date, datetime.max.time()),
        )
        .order_by(StockNewsORM.publish_time)
        .limit(5)
    )
    news_res = await db.execute(stmt_news)
    news_orms = news_res.scalars().all()
    news = [
        {
            "publish_time": n.publish_time.strftime("%Y-%m-%d"),
            "title":        n.title,
            "summary":      n.summary or "",
            "source":       n.source,
        }
        for n in news_orms
    ]

    # ── AI review ─────────────────────────────────────────────────────────────
    user = await db.get(UserORM, buy_t.user_id)
    user_name = user.name if user else "该账户"

    ai_review = await _generate_trade_review(
        stock_code=code,
        stock_name=name,
        buy_time=buy_t.trade_time,
        sell_time=sell_t.trade_time,
        buy_price=buy_t.price,
        sell_price=sell_t.price,
        quantity=buy_t.quantity,
        pnl=pnl,
        pnl_pct=pnl_pct,
        hold_days=hold_days,
        kline=kline,
        news=news,
    )

    return TradeReviewResponse(
        buy_trade_id  = buy_trade_id,
        sell_trade_id = sell_trade_id,
        stock_code    = code,
        stock_name    = name,
        buy_time      = buy_t.trade_time,
        sell_time     = sell_t.trade_time,
        buy_price     = buy_t.price,
        sell_price    = sell_t.price,
        quantity      = buy_t.quantity,
        pnl           = pnl,
        pnl_pct       = pnl_pct,
        hold_days     = hold_days,
        kline         = kline,
        news          = news,
        status        = TradeReviewStatus.COMPLETED if ai_review else TradeReviewStatus.FAILED,
        ai_review     = ai_review,
    )


# ── AI review generation ───────────────────────────────────────────────────────

async def _generate_trade_review(
    stock_code: str,
    stock_name: str,
    buy_time: datetime,
    sell_time: datetime,
    buy_price: float,
    sell_price: float,
    quantity: int,
    pnl: float,
    pnl_pct: float,
    hold_days: int,
    kline: list[dict],
    news: list[dict],
) -> Optional[str]:
    """Call LLM to generate a factual single-trade review. Returns None on failure."""
    from app.core.config import get_settings
    settings = get_settings()

    if not settings.LLM_API_KEY:
        return _fallback_review(stock_name, buy_price, sell_price, pnl, pnl_pct, hold_days, kline)

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY)

        system_prompt = (
            "你是A股交易情景还原助手，只做客观事实陈述，不做策略评判。\n"
            "用「该账户」指代投资者，禁止出现任何人名。\n"
            "输出风格：简洁、数据驱动，控制在300字以内。\n"
            "结构：① 买入时的市场背景（K线走势）② 持仓期间发生了什么（价格变化+相关资讯）③ 卖出时的市场状态 ④ 结果事实（盈亏金额/幅度）\n"
            "禁止：不要给出任何建议、评价操作好坏、或暗示应该如何做。"
        )

        # Build K-line summary (first 3 + last 3 bars to save tokens)
        if len(kline) > 6:
            kline_sample = kline[:3] + [{"...": f"共{len(kline)}个交易日"}] + kline[-3:]
        else:
            kline_sample = kline

        # News context
        if news:
            news_text = "\n".join(
                f"[{n['publish_time']}] {n['title']}：{n['summary'][:100]}…"
                for n in news
            )
        else:
            news_text = "持仓期间暂无相关资讯记录。"

        import json
        user_msg = (
            f"请对以下单笔交易进行情景还原：\n\n"
            f"股票：{stock_name}（{stock_code}）\n"
            f"买入：{buy_time.strftime('%Y-%m-%d %H:%M')}，价格 {buy_price:.2f} 元，{quantity} 股\n"
            f"卖出：{sell_time.strftime('%Y-%m-%d %H:%M')}，价格 {sell_price:.2f} 元\n"
            f"持仓：{hold_days} 个交易日\n"
            f"盈亏：{pnl:+.2f} 元（{pnl_pct:+.2f}%）\n\n"
            f"持仓期间K线（日线，部分）：\n{json.dumps(kline_sample, ensure_ascii=False)}\n\n"
            f"持仓期间相关资讯：\n{news_text}"
        )

        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.5,
            max_tokens=600,
        )
        return response.choices[0].message.content or ""

    except Exception as e:
        logger.warning("[TradeReview] LLM failed: %s — using fallback", e)
        return _fallback_review(stock_name, buy_price, sell_price, pnl, pnl_pct, hold_days, kline)


def _fallback_review(
    stock_name: str,
    buy_price: float,
    sell_price: float,
    pnl: float,
    pnl_pct: float,
    hold_days: int,
    kline: list[dict],
) -> str:
    """Template-based fallback when LLM is unavailable."""
    direction = "上涨" if sell_price > buy_price else "下跌"
    if kline:
        period_high = max(k["high"] for k in kline)
        period_low  = min(k["low"]  for k in kline)
        swing = f"持仓期间股价区间为 {period_low:.2f}～{period_high:.2f} 元，"
    else:
        swing = ""

    result_word = "盈利" if pnl >= 0 else "亏损"
    return (
        f"该账户买入{stock_name}，买入价 {buy_price:.2f} 元，"
        f"持有 {hold_days} 个交易日后以 {sell_price:.2f} 元卖出，"
        f"股价{direction} {abs(pnl_pct):.2f}%。"
        f"{swing}"
        f"本次交易{result_word} {abs(pnl):.2f} 元。"
    )
