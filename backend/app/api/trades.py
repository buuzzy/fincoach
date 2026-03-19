"""Trades API — list closed positions and generate single-trade reviews."""

from __future__ import annotations

import enum
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db, get_async_session
from app.models import TradeORM, StockNewsORM, MarketDataORM, UserORM
from app.utils.trade_utils import pair_trades

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


class TradeReviewStatus(str, enum.Enum):
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
    kline: list[dict] = []
    index_kline: list[dict] = []
    news: list[dict] = []
    status: str = TradeReviewStatus.GENERATING
    ai_review: Optional[str] = None
    error_message: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

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

    pairs = list(pair_trades(list(trades)))

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

    chart_start = buy_date - timedelta(days=14)
    chart_end   = sell_date + timedelta(days=14)

    # ── K-line from market_data (extended ±10 trading days) ─────────────────────
    stmt_kline = (
        select(MarketDataORM)
        .where(
            MarketDataORM.stock_code == code,
            MarketDataORM.trade_date >= chart_start,
            MarketDataORM.trade_date <= chart_end,
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

    # ── 上证指数 K-line (same extended range) ──────────────────────────────────
    stmt_idx = (
        select(MarketDataORM)
        .where(
            MarketDataORM.stock_code == "000001.SH",
            MarketDataORM.trade_date >= chart_start,
            MarketDataORM.trade_date <= chart_end,
        )
        .order_by(MarketDataORM.trade_date)
    )
    idx_res = await db.execute(stmt_idx)
    idx_orms = idx_res.scalars().all()
    index_kline = [
        {
            "date":       str(k.trade_date),
            "close":      k.close_price,
            "change_pct": k.change_pct,
        }
        for k in idx_orms
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
        index_kline=index_kline,
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
        index_kline   = index_kline,
        news          = news,
        status        = TradeReviewStatus.COMPLETED if ai_review else TradeReviewStatus.FAILED,
        ai_review     = ai_review,
    )


# ── AI review generation ───────────────────────────────────────────────────────

def _build_review_context(
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
    index_kline: list[dict],
) -> dict:
    """Pre-compute rich context from raw data for both LLM prompt and fallback."""
    buy_date_str  = buy_time.strftime("%Y-%m-%d")
    sell_date_str = sell_time.strftime("%Y-%m-%d")

    holding_bars = [k for k in kline if buy_date_str <= k["date"] <= sell_date_str]

    period_high = max((k["high"] for k in holding_bars), default=0)
    period_low  = min((k["low"]  for k in holding_bars), default=0)

    # Volume analysis
    volumes = [k["volume"] for k in holding_bars if k["volume"] > 0]
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    max_vol_bar = max(holding_bars, key=lambda k: k["volume"]) if holding_bars else None
    buy_bar  = next((k for k in holding_bars if k["date"] == buy_date_str), None)
    sell_bar = next((k for k in holding_bars if k["date"] == sell_date_str), None)

    vol_trend = ""
    if buy_bar and sell_bar and buy_bar["volume"] > 0:
        vol_ratio = sell_bar["volume"] / buy_bar["volume"]
        if vol_ratio > 1.5:
            vol_trend = "成交量呈放大趋势"
        elif vol_ratio < 0.6:
            vol_trend = "成交量呈缩量趋势"
        else:
            vol_trend = "成交量相对平稳"

    # Index context
    idx_summary = ""
    idx_chg = 0.0
    if index_kline:
        idx_holding = [k for k in index_kline if buy_date_str <= k["date"] <= sell_date_str]
        if idx_holding:
            idx_start = idx_holding[0]["close"]
            idx_end   = idx_holding[-1]["close"]
            idx_chg   = (idx_end - idx_start) / idx_start * 100 if idx_start else 0
            idx_summary = f"上证指数同期从 {idx_start:.2f} 到 {idx_end:.2f}（{idx_chg:+.2f}%）"

    # News
    news_lines = [f"[{n['publish_time']}] {n['title']}" for n in news]

    # Relative strength vs index
    relative = ""
    if idx_chg != 0:
        if pnl_pct > idx_chg + 2:
            relative = "跑赢大盘"
        elif pnl_pct < idx_chg - 2:
            relative = "跑输大盘"
        else:
            relative = "与大盘基本同步"

    return {
        "period_high": period_high,
        "period_low": period_low,
        "avg_vol": avg_vol,
        "max_vol_bar": max_vol_bar,
        "vol_trend": vol_trend,
        "idx_summary": idx_summary,
        "idx_chg": idx_chg,
        "relative": relative,
        "news_lines": news_lines,
        "holding_bars": holding_bars,
    }


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
    index_kline: list[dict] | None = None,
) -> Optional[str]:
    """Call LLM to generate a factual single-trade review. Returns None on failure."""
    if index_kline is None:
        index_kline = []

    ctx = _build_review_context(
        stock_code, stock_name, buy_time, sell_time,
        buy_price, sell_price, quantity, pnl, pnl_pct, hold_days,
        kline, news, index_kline,
    )

    from app.core.config import get_settings
    settings = get_settings()

    if not settings.LLM_API_KEY:
        return _fallback_review(
            stock_name, buy_price, sell_price, pnl, pnl_pct, hold_days, ctx)

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY)

        system_prompt = (
            "你是A股交易情景还原助手，基于提供的数据做客观事实陈述。\n"
            "用「该账户」指代投资者，禁止出现任何人名。\n"
            "输出风格：专业、数据驱动，400~600字。\n"
            "输出格式：纯文本，用序号（①②③④）分段，禁止使用任何 Markdown 格式"
            "（如 **加粗**、## 标题、- 列表等）。\n"
            "输出结构：\n"
            "① 买入背景：买入当日大盘状态、个股走势、成交量特征\n"
            "② 持仓过程：逐步描述期间股价和成交量的关键变化，结合同期资讯事件（如有），"
            "与大盘走势对比（跑赢/跑输/同步）\n"
            "③ 卖出时的市场状态\n"
            "④ 交易结果：盈亏金额和幅度\n"
            "禁止给出任何策略建议或操作评价。"
        )

        # K-line digest for holding period
        holding = ctx["holding_bars"]
        if len(holding) > 8:
            kline_digest = holding[:3] + [{"...": f"共{len(holding)}个交易日"}] + holding[-3:]
        else:
            kline_digest = holding

        news_text = "\n".join(ctx["news_lines"]) if ctx["news_lines"] else "持仓期间暂无相关资讯。"

        user_msg = (
            f"请对以下交易进行情景还原分析：\n\n"
            f"【交易信息】\n"
            f"股票：{stock_name}（{stock_code}）\n"
            f"买入：{buy_time.strftime('%Y-%m-%d %H:%M')}，{buy_price:.2f} 元 × {quantity} 股\n"
            f"卖出：{sell_time.strftime('%Y-%m-%d %H:%M')}，{sell_price:.2f} 元\n"
            f"持仓天数：{hold_days}天 | 盈亏：{pnl:+.2f} 元（{pnl_pct:+.2f}%）\n\n"
            f"【持仓期间行情】\n"
            f"股价区间：{ctx['period_low']:.2f} ~ {ctx['period_high']:.2f}\n"
            f"成交量特征：{ctx['vol_trend']}\n"
            f"逐日数据：\n{json.dumps(kline_digest, ensure_ascii=False)}\n\n"
            f"【大盘参考】\n"
            f"{ctx['idx_summary'] or '暂无大盘数据'}\n"
            f"个股相对表现：{ctx['relative'] or '无法比较'}\n\n"
            f"【持仓期间资讯】\n{news_text}"
        )

        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.5,
            max_tokens=4000,
        )
        choice = response.choices[0] if response.choices else None
        if choice:
            content = (choice.message.content or "").strip()
            finish = getattr(choice, "finish_reason", None)
            logger.info("[TradeReview] LLM finish_reason=%s content_len=%d", finish, len(content))
            if content:
                return content
        else:
            logger.warning("[TradeReview] LLM returned 0 choices")
        logger.warning("[TradeReview] LLM returned empty content — using fallback")

    except Exception as e:
        logger.warning("[TradeReview] LLM failed: %s — using fallback", e, exc_info=True)

    return _fallback_review(
        stock_name, buy_price, sell_price, pnl, pnl_pct, hold_days, ctx)


def _fallback_review(
    stock_name: str,
    buy_price: float,
    sell_price: float,
    pnl: float,
    pnl_pct: float,
    hold_days: int,
    ctx: dict,
) -> str:
    """Rich template-based fallback when LLM is unavailable."""
    direction = "上涨" if sell_price > buy_price else "下跌"
    result_word = "盈利" if pnl >= 0 else "亏损"

    parts = [
        f"该账户买入{stock_name}，买入价 {buy_price:.2f} 元，"
        f"持有 {hold_days} 个交易日后以 {sell_price:.2f} 元卖出，"
        f"股价{direction} {abs(pnl_pct):.2f}%。"
    ]

    if ctx.get("period_high") and ctx.get("period_low"):
        parts.append(
            f"持仓期间股价波动区间为 {ctx['period_low']:.2f} ~ {ctx['period_high']:.2f} 元。"
        )

    if ctx.get("vol_trend"):
        parts.append(f"期间{ctx['vol_trend']}。")

    if ctx.get("idx_summary"):
        parts.append(f"同期{ctx['idx_summary']}，个股{ctx.get('relative', '')}。")

    if ctx.get("news_lines"):
        parts.append("持仓期间相关资讯：" + "；".join(
            line.split("] ", 1)[1] if "] " in line else line
            for line in ctx["news_lines"][:3]
        ) + "。")

    parts.append(f"本次交易{result_word} {abs(pnl):.2f} 元。")

    return "\n".join(parts)
