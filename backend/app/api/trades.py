"""Trades API — list closed positions and generate single-trade reviews."""

from __future__ import annotations

import enum
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db, get_async_session
from app.models import TradeORM, StockNewsORM, MarketDataORM, UserORM
from app.utils.trade_utils import pair_trades

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trades", tags=["trades"])

FLP_BASE = "https://papi-uat.finloopg.com/flp-mktdata-hub"
_INDUSTRY_CACHE: dict[str, tuple[str, str]] = {}  # stock_code → (industry_code, industry_name)


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
    sector_kline: list[dict] = []
    sector_name: str = ""
    news: list[dict] = []
    status: str = TradeReviewStatus.GENERATING
    ai_review: Optional[str] = None
    error_message: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hold_days(buy_time: datetime, sell_time: datetime) -> int:
    return max(1, (sell_time.date() - buy_time.date()).days)


async def _get_industry_info(stock_code: str) -> tuple[str, str] | None:
    """Return (industry_code, industry_name) via flp-mktdata, with in-memory cache."""
    if stock_code in _INDUSTRY_CACHE:
        return _INDUSTRY_CACHE[stock_code]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{FLP_BASE}/v1/stock/company/info",
                json={"ticker": stock_code},
            )
            data = resp.json()
            code = data.get("industryCode")
            name = data.get("industryName")
            if code and name:
                _INDUSTRY_CACHE[stock_code] = (code, name)
                return (code, name)
    except Exception as e:
        logger.warning("[SectorInfo] Failed to get industry for %s: %s", stock_code, e)
    return None


async def _fetch_sector_kline(
    db: AsyncSession,
    industry_code: str,
    industry_name: str,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Return sector index K-line: read from market_data cache, fetch from API if missing."""
    stmt = (
        select(MarketDataORM)
        .where(
            MarketDataORM.stock_code == industry_code,
            MarketDataORM.trade_date >= start_date,
            MarketDataORM.trade_date <= end_date,
        )
        .order_by(MarketDataORM.trade_date)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if rows:
        return [
            {"date": str(r.trade_date), "close": r.close_price, "change_pct": r.change_pct}
            for r in rows
        ]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{FLP_BASE}/v1/stock/history",
                json={
                    "code": industry_code,
                    "startDate": str(start_date),
                    "endDate": str(end_date),
                },
            )
            bars = resp.json().get("data", [])
            if not bars:
                return []

            for bar in bars:
                db.add(MarketDataORM(
                    stock_code=industry_code,
                    stock_name=industry_name,
                    trade_date=date.fromisoformat(bar["time"]),
                    open_price=bar["open"],
                    high_price=bar["high"],
                    low_price=bar["low"],
                    close_price=bar["close"],
                    volume=bar.get("vol", 0),
                    change_pct=bar.get("chgPct", 0),
                ))
            await db.commit()
            logger.info("[SectorKline] Cached %d bars for %s (%s)", len(bars), industry_code, industry_name)

            return [
                {"date": bar["time"], "close": bar["close"], "change_pct": bar.get("chgPct", 0)}
                for bar in bars
            ]
    except Exception as e:
        logger.warning("[SectorKline] Failed for %s: %s", industry_code, e)
        return []


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

    # ── 行业板块 K-line ────────────────────────────────────────────────────────
    sector_kline: list[dict] = []
    sector_name = ""
    industry = await _get_industry_info(code)
    if industry:
        sector_code, sector_name = industry
        sector_kline = await _fetch_sector_kline(db, sector_code, sector_name, chart_start, chart_end)

    # ── News from stock_news (expand window ±3 days for better coverage) ────────
    news_start = datetime.combine(buy_date - timedelta(days=3), datetime.min.time())
    news_end = datetime.combine(sell_date + timedelta(days=3), datetime.max.time())
    stmt_news = (
        select(StockNewsORM)
        .where(
            StockNewsORM.stock_code == code,
            StockNewsORM.publish_time >= news_start,
            StockNewsORM.publish_time <= news_end,
        )
        .order_by(StockNewsORM.publish_time)
        .limit(10)
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
        sector_kline=sector_kline,
        sector_name=sector_name,
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
        sector_kline  = sector_kline,
        sector_name   = sector_name,
        news          = news,
        status        = TradeReviewStatus.COMPLETED if ai_review else TradeReviewStatus.FAILED,
        ai_review     = ai_review,
    )


# ── AI review generation ───────────────────────────────────────────────────────

def _filter_relevant_news(news: list[dict], stock_name: str) -> list[dict]:
    """Keep only news whose title mentions the stock or closely related terms."""
    base_name = stock_name.replace("（", "").replace("）", "").strip()
    short_names = [base_name]
    if len(base_name) >= 4:
        short_names.append(base_name[:2])

    relevant: list[dict] = []
    for n in news:
        title = n.get("title", "")
        if any(kw in title for kw in short_names):
            relevant.append(n)
    return relevant if relevant else news[:3]


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
    sector_kline: list[dict] | None = None,
    sector_name: str = "",
) -> dict:
    """Pre-compute rich analytical context from raw data."""
    buy_date_str  = buy_time.strftime("%Y-%m-%d")
    sell_date_str = sell_time.strftime("%Y-%m-%d")

    holding_bars = [k for k in kline if buy_date_str <= k["date"] <= sell_date_str]

    period_high = max((k["high"] for k in holding_bars), default=0)
    period_low  = min((k["low"]  for k in holding_bars), default=0)

    # ── Volume analysis ──
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

    # ── Index context ──
    idx_summary = ""
    idx_chg = 0.0
    if index_kline:
        idx_holding = [k for k in index_kline if buy_date_str <= k["date"] <= sell_date_str]
        if idx_holding:
            idx_start = idx_holding[0]["close"]
            idx_end   = idx_holding[-1]["close"]
            idx_chg   = (idx_end - idx_start) / idx_start * 100 if idx_start else 0
            idx_summary = f"上证指数同期从 {idx_start:.2f} 到 {idx_end:.2f}（{idx_chg:+.2f}%）"

    # ── Relative strength ──
    relative = ""
    if idx_chg != 0:
        if pnl_pct > idx_chg + 2:
            relative = "显著跑赢大盘"
        elif pnl_pct < idx_chg - 2:
            relative = "明显跑输大盘"
        else:
            relative = "与大盘基本同步"

    # ── Sector context ──
    sector_summary = ""
    sector_chg = 0.0
    if sector_kline and sector_name:
        sect_holding = [k for k in sector_kline if buy_date_str <= k["date"] <= sell_date_str]
        if sect_holding:
            sect_start = sect_holding[0]["close"]
            sect_end = sect_holding[-1]["close"]
            sector_chg = (sect_end - sect_start) / sect_start * 100 if sect_start else 0
            sector_summary = f"{sector_name}板块同期涨跌 {sector_chg:+.2f}%"

    # ── Timing quality analysis ──
    buy_vs_low = ((buy_price - period_low) / period_low * 100) if period_low else 0
    sell_vs_high = ((period_high - sell_price) / period_high * 100) if period_high else 0

    buy_timing = ""
    if buy_vs_low < 3:
        buy_timing = "接近区间最低点，买入时机较好"
    elif buy_vs_low < 10:
        buy_timing = "处于区间偏低位置"
    elif buy_vs_low > 20:
        buy_timing = "处于区间中高位置，追高风险较大"
    else:
        buy_timing = "处于区间中间位置"

    sell_timing = ""
    if sell_vs_high < 3:
        sell_timing = "接近区间最高点，卖出时机较好"
    elif sell_vs_high < 10:
        sell_timing = "处于区间偏高位置"
    elif sell_vs_high > 20:
        sell_timing = "距区间高点较远，可能过早离场"
    else:
        sell_timing = "处于区间中间位置"

    # ── Max drawdown / max unrealized gain ──
    max_drawdown = 0.0
    max_drawdown_date = ""
    max_float_gain = 0.0
    max_float_gain_date = ""
    for k in holding_bars:
        dd = (k["low"] - buy_price) / buy_price * 100
        if dd < max_drawdown:
            max_drawdown = dd
            max_drawdown_date = k["date"]
        fg = (k["high"] - buy_price) / buy_price * 100
        if fg > max_float_gain:
            max_float_gain = fg
            max_float_gain_date = k["date"]

    # ── Key events: biggest daily moves & volume spikes ──
    key_events: list[dict] = []
    sorted_by_chg = sorted(holding_bars, key=lambda k: abs(k.get("change_pct", 0)), reverse=True)
    for k in sorted_by_chg[:3]:
        if abs(k.get("change_pct", 0)) >= 2.0:
            key_events.append({
                "date": k["date"],
                "type": "大涨" if k["change_pct"] > 0 else "大跌",
                "change_pct": k["change_pct"],
                "close": k["close"],
                "volume": k["volume"],
            })

    vol_spikes: list[dict] = []
    if avg_vol > 0:
        for k in holding_bars:
            if k["volume"] > avg_vol * 2:
                vol_spikes.append({
                    "date": k["date"],
                    "volume": k["volume"],
                    "ratio": round(k["volume"] / avg_vol, 1),
                    "change_pct": k.get("change_pct", 0),
                })

    # ── Trend phases ──
    trend_desc = ""
    if len(holding_bars) >= 5:
        mid = len(holding_bars) // 2
        first_half_chg = (holding_bars[mid]["close"] - holding_bars[0]["close"]) / holding_bars[0]["close"] * 100
        second_half_chg = (holding_bars[-1]["close"] - holding_bars[mid]["close"]) / holding_bars[mid]["close"] * 100
        if first_half_chg > 3 and second_half_chg > 3:
            trend_desc = "持仓期间整体呈持续上涨走势"
        elif first_half_chg < -3 and second_half_chg > 5:
            trend_desc = "前半段下跌后半段反弹，走出V型"
        elif first_half_chg > 5 and second_half_chg < -3:
            trend_desc = "前半段上涨后半段回落，走出倒V型"
        elif first_half_chg < -3 and second_half_chg < -3:
            trend_desc = "持仓期间整体呈持续下跌走势"
        else:
            trend_desc = "持仓期间股价呈震荡走势"

    # ── Filter news by relevance ──
    relevant_news = _filter_relevant_news(news, stock_name)
    news_lines = [f"[{n['publish_time']}] {n['title']}" for n in relevant_news]

    return {
        "period_high": period_high,
        "period_low": period_low,
        "avg_vol": avg_vol,
        "max_vol_bar": max_vol_bar,
        "vol_trend": vol_trend,
        "idx_summary": idx_summary,
        "idx_chg": idx_chg,
        "relative": relative,
        "sector_summary": sector_summary,
        "sector_chg": sector_chg,
        "sector_name": sector_name,
        "news_lines": news_lines,
        "holding_bars": holding_bars,
        "buy_timing": buy_timing,
        "sell_timing": sell_timing,
        "buy_vs_low": buy_vs_low,
        "sell_vs_high": sell_vs_high,
        "max_drawdown": max_drawdown,
        "max_drawdown_date": max_drawdown_date,
        "max_float_gain": max_float_gain,
        "max_float_gain_date": max_float_gain_date,
        "key_events": key_events,
        "vol_spikes": vol_spikes,
        "trend_desc": trend_desc,
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
    sector_kline: list[dict] | None = None,
    sector_name: str = "",
) -> Optional[str]:
    """Call LLM to generate a factual single-trade review. Returns None on failure."""
    if index_kline is None:
        index_kline = []
    if sector_kline is None:
        sector_kline = []

    ctx = _build_review_context(
        stock_code, stock_name, buy_time, sell_time,
        buy_price, sell_price, quantity, pnl, pnl_pct, hold_days,
        kline, news, index_kline, sector_kline, sector_name,
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
            "你是A股交易复盘分析师。基于数据还原交易情景，帮助投资者理解走势背后的原因。\n\n"
            "规则：\n"
            "- 用「该账户」指代投资者，禁止人名\n"
            "- 总字数 200~300 字，精炼扼要，每段 2-3 句\n"
            "- 禁止 Markdown 格式（无 **、##、- 列表）\n"
            "- 将数据自然融入叙述，不要罗列数字\n"
            "- 禁止给出策略建议或操作评价\n\n"
            "严格按以下 4 段输出，每段以【】标题开头：\n\n"
            "【买入时点】买入时个股位于区间什么位置，大盘和量能状态如何，"
            "结合资讯分析买入背景。\n\n"
            "【持仓历程】识别 1-2 个关键转折点，说明驱动因素，"
            "将资讯与股价变动建立因果联系。\n\n"
            "【卖出时点】卖出价距区间高点的位置，"
            "是趋势中止盈还是回调离场。\n\n"
            "【交易复盘】总结风险收益比，"
            "最大浮亏和最大浮盈各多少，最终兑现了多少。"
        )

        # K-line digest: keep key days rather than just head/tail
        holding = ctx["holding_bars"]
        if len(holding) > 12:
            kline_digest = holding[:3] + holding[len(holding)//2-1:len(holding)//2+2] + holding[-3:]
        elif len(holding) > 8:
            kline_digest = holding[:3] + holding[-3:]
        else:
            kline_digest = holding

        news_text = "\n".join(ctx["news_lines"]) if ctx["news_lines"] else "持仓期间暂无相关资讯。"

        # Key events summary
        events_text = ""
        if ctx["key_events"]:
            events_lines = [
                f"  {e['date']}: {e['type']} {e['change_pct']:+.2f}%，收于{e['close']:.2f}元"
                for e in ctx["key_events"]
            ]
            events_text = "关键行情事件：\n" + "\n".join(events_lines)

        vol_spike_text = ""
        if ctx["vol_spikes"]:
            spike_lines = [
                f"  {s['date']}: 成交量达均量{s['ratio']}倍，当日涨跌 {s['change_pct']:+.2f}%"
                for s in ctx["vol_spikes"][:3]
            ]
            vol_spike_text = "成交量异动：\n" + "\n".join(spike_lines)

        user_msg = (
            f"请对以下交易进行深度情景还原分析：\n\n"
            f"【交易概况】\n"
            f"股票：{stock_name}（{stock_code}）\n"
            f"买入：{buy_time.strftime('%Y-%m-%d')}，{buy_price:.2f} 元 × {quantity} 股\n"
            f"卖出：{sell_time.strftime('%Y-%m-%d')}，{sell_price:.2f} 元\n"
            f"持仓天数：{hold_days}天 | 盈亏：{pnl:+.2f} 元（{pnl_pct:+.2f}%）\n\n"
            f"【行情分析要素】\n"
            f"股价区间：{ctx['period_low']:.2f} ~ {ctx['period_high']:.2f}\n"
            f"走势形态：{ctx['trend_desc']}\n"
            f"成交量趋势：{ctx['vol_trend']}\n"
            f"买入位置：买入价距区间低点 {ctx['buy_vs_low']:.1f}%，{ctx['buy_timing']}\n"
            f"卖出位置：卖出价距区间高点 {ctx['sell_vs_high']:.1f}%，{ctx['sell_timing']}\n"
            f"最大浮亏：{ctx['max_drawdown']:.2f}%"
            f"{'（' + ctx['max_drawdown_date'] + '）' if ctx['max_drawdown_date'] else ''}\n"
            f"最大浮盈：{ctx['max_float_gain']:.2f}%"
            f"{'（' + ctx['max_float_gain_date'] + '）' if ctx['max_float_gain_date'] else ''}\n"
            f"{events_text}\n"
            f"{vol_spike_text}\n\n"
            f"【逐日K线摘要】\n{json.dumps(kline_digest, ensure_ascii=False)}\n\n"
            f"【大盘参考】\n"
            f"{ctx['idx_summary'] or '暂无大盘数据'}\n"
            f"个股相对表现：{ctx['relative'] or '无法比较'}\n\n"
            f"【板块参考】\n"
            f"{ctx['sector_summary'] or '暂无板块数据'}\n\n"
            f"【持仓期间相关资讯】\n{news_text}"
        )

        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.5,
            max_tokens=1500,
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
    """Structured fallback with 【】 section headers when LLM is unavailable."""
    result_word = "盈利" if pnl >= 0 else "亏损"

    sections: list[str] = []

    # ── 买入时点 ──
    p1 = f"【买入时点】该账户以 {buy_price:.2f} 元买入{stock_name}"
    if ctx.get("buy_timing"):
        p1 += f"，买入价{ctx['buy_timing']}"
    p1 += "。"
    if ctx.get("idx_summary"):
        p1 += f"同期{ctx['idx_summary']}。"
    if ctx.get("sector_summary"):
        p1 += f"{ctx['sector_summary']}。"
    sections.append(p1)

    # ── 持仓历程 ──
    p2 = f"【持仓历程】持仓 {hold_days} 个交易日，"
    if ctx.get("trend_desc"):
        p2 += f"{ctx['trend_desc']}。"
    else:
        p2 += f"股价在 {ctx['period_low']:.2f} ~ {ctx['period_high']:.2f} 元区间波动。"
    key_events = ctx.get("key_events", [])
    if key_events:
        e = key_events[0]
        p2 += f"关键节点：{e['date']}{e['type']}{abs(e['change_pct']):.2f}%。"
    if ctx.get("relative"):
        p2 += f"个股表现{ctx['relative']}。"
    sections.append(p2)

    # ── 卖出时点 ──
    p3 = f"【卖出时点】以 {sell_price:.2f} 元卖出"
    if ctx.get("sell_timing"):
        p3 += f"，{ctx['sell_timing']}"
    p3 += "。"
    if ctx.get("max_float_gain") and ctx["max_float_gain"] > pnl_pct + 5:
        p3 += f"最高浮盈 {ctx['max_float_gain']:.2f}%，最终兑现 {pnl_pct:.2f}%，有一定回吐。"
    sections.append(p3)

    # ── 交易复盘 ──
    p4 = f"【交易复盘】本次交易{result_word} {abs(pnl):.2f} 元（{pnl_pct:+.2f}%）。"
    if ctx.get("max_drawdown") and ctx["max_drawdown"] < -3:
        p4 += f"期间最大浮亏 {ctx['max_drawdown']:.2f}%。"
    if pnl >= 0 and ctx.get("idx_chg") is not None:
        excess = pnl_pct - ctx["idx_chg"]
        if excess > 5:
            p4 += f"超额收益 {excess:.2f}%。"
    sections.append(p4)

    return "\n\n".join(sections)
