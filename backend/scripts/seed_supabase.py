"""One-shot seed script — inserts fixed demo data directly into Supabase.

Run once from the backend directory:
    python scripts/seed_supabase.py

Requirements:
    pip install asyncpg sqlalchemy pydantic-settings python-dotenv httpx

After this script completes successfully, set FORCE_RESEED=false in Render
and the data will never be touched again.
"""

from __future__ import annotations

import asyncio
import logging
import random
import sys
import os
from datetime import datetime, date, timedelta
from typing import Any

# ── Allow imports from parent package ────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── DB connection ─────────────────────────────────────────────────────────────
DB_URL = os.environ["DATABASE_URL"]  # must be postgresql+asyncpg://...

# ── A股手续费常数 ──────────────────────────────────────────────────────────────
COMMISSION_RATE = 0.0003   # 佣金 0.03%（买卖双向）
STAMP_DUTY_RATE  = 0.001   # 印花税 0.10%（仅卖出）

def buy_fee(amount: float) -> float:
    return amount * COMMISSION_RATE

def sell_fee(amount: float) -> float:
    return amount * (COMMISSION_RATE + STAMP_DUTY_RATE)

def calc_pnl(buy_price: float, sell_price: float, qty: int) -> tuple[float, float]:
    """Return (pnl_yuan, pnl_pct) including all fees."""
    buy_cost  = buy_price  * qty + buy_fee(buy_price * qty)
    sell_recv = sell_price * qty - sell_fee(sell_price * qty)
    pnl       = round(sell_recv - buy_cost, 2)
    pnl_pct   = round((sell_price - buy_price) / buy_price * 100, 2)
    return pnl, pnl_pct

def price_aware_qty(price: float, target_value: float) -> int:
    """Return nearest 100-lot quantity for given target notional, min 100."""
    raw = target_value / price
    return max(100, round(raw / 100) * 100)

# ── Stock universe ────────────────────────────────────────────────────────────
# 选股原则：涨跌互现、风格多元（消费/新能源/半导体/军工/光伏/安防/电力）
STOCKS: list[tuple[str, str]] = [
    ("600519.SH", "贵州茅台"),    # 白酒消费，+1.1%
    ("002594.SZ", "比亚迪"),      # 新能源整车，+3.7%
    ("300750.SZ", "宁德时代"),    # 锂电池，+12.2%
    ("688008.SH", "澜起科技"),    # 半导体/AI算力，+10.6%
    ("600893.SH", "航发动力"),    # 军工/航空发动机，+30.4%
    ("688390.SH", "固德威"),      # 光伏逆变器，+36.6%
    ("601888.SH", "中国中免"),    # 免税消费，-18.6%
    ("600900.SH", "长江电力"),    # 水电公用，+2.3%
    ("002415.SZ", "海康威视"),    # 安防科技，+1.6%
    ("300285.SZ", "国瓷材料"),    # 新材料小盘，+20.2%
]
STOCK_MAP = {code: name for code, name in STOCKS}

INDEX_CODE = "000001.SH"
INDEX_NAME = "上证指数"

# 个股新闻不足时的板块补充关键词（精准对应，避免误匹配）
STOCK_SECTOR_KEYWORDS: dict[str, str] = {
    "002415.SZ": "安防",          # 海康威视 → 安防板块
    "600893.SH": "航空航天",      # 航发动力 → 航空航天军工
    "300285.SZ": "新材料",        # 国瓷材料 → 新材料板块
    "688390.SH": "光伏",          # 固德威 → 光伏板块
}

PERIOD_START = date(2026, 1, 14)
PERIOD_END   = date(2026, 3, 14)

# ── Users ─────────────────────────────────────────────────────────────────────
USERS = [
    (1, "华泰****3821", "aggressive"),
    (2, "招商****0712", "conservative"),
    (3, "东财****5967", "emotional"),
    (4, "中信****2483", "balanced"),
    (5, "海通****8156", "balanced"),
]

# ── flp-mktdata K-line fetch ──────────────────────────────────────────────────
FLP_MKTDATA_BASE = "https://papi-uat.finloopg.com/flp-mktdata-hub"

async def fetch_kline_flp(code: str) -> list[dict[str, Any]]:
    """Fetch daily K-line from flp-mktdata (primary)."""
    import httpx
    url = f"{FLP_MKTDATA_BASE}/v1/stock/history"
    payload = {
        "code": code,
        "startDate": PERIOD_START.strftime("%Y-%m-%d"),
        "endDate":   PERIOD_END.strftime("%Y-%m-%d"),
        "ktype": "day",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        data = resp.json()

    rows = []
    for r in data.get("data", []):
        try:
            d = date.fromisoformat(str(r["time"])[:10])
            rows.append({
                "date":       d,
                "open":       float(r.get("open")  or 0),
                "high":       float(r.get("high")  or 0),
                "low":        float(r.get("low")   or 0),
                "close":      float(r.get("close") or 0),
                "volume":     float(r.get("vol")   or 0),
                "change_pct": float(r.get("chgPct") or 0),
            })
        except Exception:
            continue
    logger.info("  flp-mktdata %s → %d rows", code, len(rows))
    return rows


async def fetch_kline_qveris(code: str) -> list[dict[str, Any]]:
    """Fetch daily K-line from QVeris (fallback)."""
    from app.services.qveris_client import get_key_pool
    pool = get_key_pool()
    tool_id, search_id = await pool.search(
        f"A股历史K线 {code}",
        preferred_tool_id="ths_ifind.history_quotation.v1",
    )
    resp = await pool.execute(tool_id, search_id, {
        "codes":      code,
        "indicators": "open,high,low,close,volume,changeRatio",
        "startdate":  PERIOD_START.strftime("%Y-%m-%d"),
        "enddate":    PERIOD_END.strftime("%Y-%m-%d"),
        "interval":   "D",
    })
    if not resp.get("success"):
        return []

    raw = resp.get("result", {}).get("data") or resp.get("data")
    row_list: list[dict] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, list):
                row_list.extend(item)
            elif isinstance(item, dict):
                row_list.append(item)

    rows = []
    for r in row_list:
        try:
            d = date.fromisoformat(str(r.get("time") or r.get("date", ""))[:10])
            rows.append({
                "date":       d,
                "open":       float(r.get("open")  or 0),
                "high":       float(r.get("high")  or 0),
                "low":        float(r.get("low")   or 0),
                "close":      float(r.get("close") or 0),
                "volume":     float(r.get("volume") or 0),
                "change_pct": float(r.get("changeRatio") or 0),
            })
        except Exception:
            continue
    logger.info("  QVeris %s → %d rows", code, len(rows))
    return rows


async def fetch_kline(code: str, qveris_available: bool) -> list[dict[str, Any]]:
    """Primary: flp-mktdata. Fallback: QVeris. Final fallback: synthetic."""
    # Primary: flp-mktdata
    try:
        rows = await fetch_kline_flp(code)
        if rows:
            return rows
        logger.warning("  flp-mktdata %s returned 0 rows, trying QVeris", code)
    except Exception as e:
        logger.warning("  flp-mktdata %s failed: %s, trying QVeris", code, e)

    # Fallback: QVeris
    if qveris_available:
        try:
            rows = await fetch_kline_qveris(code)
            if rows:
                return rows
            logger.warning("  QVeris %s returned 0 rows, using synthetic", code)
        except Exception as e:
            logger.warning("  QVeris %s failed: %s, using synthetic", code, e)

    # Final fallback: synthetic
    logger.warning("  Using synthetic K-line for %s", code)
    return synthetic_kline(code)


# ── finloop-news fetch ─────────────────────────────────────────────────────────
FINLOOP_NEWS_BASE = "https://ai-uat.finloopfintech.com"

async def fetch_news_finloop(stock_name: str, stock_code: str) -> list[dict[str, Any]]:
    """Fetch stock news from finloop-news (primary).

    If individual stock returns fewer than 5 in-period articles,
    supplement with sector-level news using the per-stock keyword map.
    """
    import httpx

    async def _query(keyword: str, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        url = f"{FINLOOP_NEWS_BASE}/flp-news-api/v1/news-agent/informationList"
        payload = {"category": "stock", "keyword": keyword, "page_size": 20}
        resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("information_list", [])
        rows = []
        for item in items:
            try:
                pt_str = item.get("publish_time", "")
                if not pt_str:
                    continue
                pt = datetime.fromisoformat(pt_str.replace("Z", "+00:00")).replace(tzinfo=None)
                if not (PERIOD_START <= pt.date() <= PERIOD_END):
                    continue
                rows.append({
                    "publish_time": pt,
                    "title":        item.get("title", "").strip(),
                    "summary":      item.get("summary", "").strip(),
                    "source":       "finloop",
                })
            except Exception:
                continue
        return rows

    async with httpx.AsyncClient(timeout=30.0) as client:
        rows = await _query(stock_name, client)
        logger.info("  finloop-news %s(%s) 个股 → %d 条", stock_name, stock_code, len(rows))

        # Supplement with sector news if fewer than 5 articles
        sector_kw = STOCK_SECTOR_KEYWORDS.get(stock_code)
        if sector_kw and len(rows) < 5:
            sector_rows = await _query(sector_kw, client)
            # Deduplicate by title
            existing_titles = {r["title"] for r in rows}
            added = [r for r in sector_rows if r["title"] not in existing_titles]
            rows.extend(added)
            logger.info("  finloop-news %s(%s) 板块「%s」补充 → +%d 条，合计 %d 条",
                        stock_name, stock_code, sector_kw, len(added), len(rows))

    return rows


# ── Synthetic K-line fallback ─────────────────────────────────────────────────
_SEED_PRICES = {
    "600519.SH": 1400.0, "002594.SZ": 96.0,  "300750.SZ": 225.0,
    "688008.SH": 65.0,   "600893.SH": 38.0,  "688390.SH": 50.0,
    "601888.SH": 90.0,   "600900.SH": 27.0,  "002415.SZ": 31.0,
    "300285.SZ": 20.0,
}

def _trading_days(start: date, end: date) -> list[date]:
    days, cur = [], start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days

def synthetic_kline(code: str) -> list[dict[str, Any]]:
    rng = random.Random(hash(code) & 0xFFFFFFFF)
    price = _SEED_PRICES.get(code, 50.0)
    rows = []
    for d in _trading_days(PERIOD_START, PERIOD_END):
        chg   = max(min(rng.gauss(0, 2.0), 9.9), -9.9)
        close = round(price * (1 + chg / 100), 2)
        high  = round(max(price, close) * (1 + rng.uniform(0, 0.015)), 2)
        low   = round(min(price, close) * (1 - rng.uniform(0, 0.015)), 2)
        opn   = round(price * (1 + rng.uniform(-0.005, 0.005)), 2)
        vol   = round(rng.uniform(50000, 500000) * (price / 50))
        rows.append({"date": d, "open": opn, "high": high, "low": low,
                     "close": close, "volume": vol, "change_pct": round(chg, 2)})
        price = close
    return rows


# ── Trade generation ──────────────────────────────────────────────────────────

PROFILE_CFG = {
    "aggressive":   dict(n=(18, 22), hold=(1, 5),   targets=[30000, 50000, 80000, 100000], buy_bias=(1.01, 1.05), sell_noise=(-0.02, 0.02)),
    "conservative": dict(n=(8,  12), hold=(15, 35),  targets=[50000, 80000, 100000, 150000], buy_bias=(0.98, 1.02), sell_noise=(-0.01, 0.01)),
    "emotional":    dict(n=(14, 18), hold=(2, 20),   targets=[30000, 50000, 80000],          buy_bias=(1.02, 1.07), sell_noise=(-0.02, 0.01)),
    "balanced":     dict(n=(10, 14), hold=(3, 15),   targets=[50000, 80000, 100000],         buy_bias=(0.99, 1.02), sell_noise=(-0.01, 0.01)),
}

def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))

def make_time(d: date, rng: random.Random) -> datetime:
    return datetime.combine(d, datetime.min.time().replace(
        hour=rng.randint(9, 14), minute=rng.randint(30, 59)))

def generate_trades(user_id: int, profile: str, kline_map: dict, rng: random.Random) -> list[dict]:
    cfg = PROFILE_CFG[profile]
    available = list(kline_map.keys())
    stocks = rng.sample(available, k=min(rng.randint(4, 7), len(available)))
    n_trips = rng.randint(*cfg["n"])
    trades = []

    for _ in range(n_trips):
        code  = rng.choice(stocks)
        rows  = kline_map[code]
        if len(rows) < 5:
            continue

        hold = rng.randint(*cfg["hold"])
        buy_idx  = rng.randint(3, max(4, len(rows) - hold - 3))
        sell_idx = min(buy_idx + hold, len(rows) - 1)
        if sell_idx <= buy_idx:
            continue

        br, sr = rows[buy_idx], rows[sell_idx]

        raw_buy  = br["close"] * rng.uniform(*cfg["buy_bias"])
        buy_price = round(clamp(raw_buy, br["low"], br["high"]), 2)

        raw_sell = sr["close"] * (1 + rng.uniform(*cfg["sell_noise"]))
        sell_price = round(clamp(raw_sell, sr["low"], sr["high"]), 2)

        target = rng.choice(cfg["targets"])
        qty    = price_aware_qty(buy_price, target)

        pnl, pnl_pct = calc_pnl(buy_price, sell_price, qty)

        trades.append(dict(user_id=user_id, stock_code=code, stock_name=STOCK_MAP[code],
                           direction="buy",  price=buy_price,  quantity=qty,
                           trade_time=make_time(br["date"], rng), pnl=None, pnl_pct=None))
        trades.append(dict(user_id=user_id, stock_code=code, stock_name=STOCK_MAP[code],
                           direction="sell", price=sell_price, quantity=qty,
                           trade_time=make_time(sr["date"], rng), pnl=pnl, pnl_pct=pnl_pct))
    return trades


def generate_zhaoxin_trades(user_id: int, kline_map: dict, rng: random.Random) -> list[dict]:
    """6-8 trades for 海通****8156, guaranteed slow_stop_loss + chase_high patterns."""
    available = list(kline_map.keys())
    stocks = rng.sample(available, k=min(2, len(available)))
    trades = []

    def add(code, buy_idx, sell_idx, buy_override=None, sell_override=None):
        rows = kline_map.get(code, [])
        if not rows or sell_idx >= len(rows) or buy_idx >= sell_idx:
            return
        br, sr = rows[buy_idx], rows[sell_idx]
        bp = buy_override  or round(clamp(br["close"] * 1.01, br["low"], br["high"]), 2)
        sp = sell_override or round(clamp(sr["close"] * 0.99, sr["low"], sr["high"]), 2)
        qty = price_aware_qty(bp, 50000)
        pnl, pnl_pct = calc_pnl(bp, sp, qty)
        trades.append(dict(user_id=user_id, stock_code=code, stock_name=STOCK_MAP.get(code, code),
                           direction="buy",  price=bp, quantity=qty,
                           trade_time=make_time(br["date"], rng), pnl=None, pnl_pct=None))
        trades.append(dict(user_id=user_id, stock_code=code, stock_name=STOCK_MAP.get(code, code),
                           direction="sell", price=sp, quantity=qty,
                           trade_time=make_time(sr["date"], rng), pnl=pnl, pnl_pct=pnl_pct))

    c0 = stocks[0] if stocks else available[0]
    c1 = stocks[1] if len(stocks) > 1 else c0
    rows0, rows1 = kline_map.get(c0, []), kline_map.get(c1, [])

    # slow_stop_loss: -12% loss
    if len(rows0) >= 22:
        bp = round(rows0[3]["close"] * 1.03, 2)
        sp = round(clamp(bp * 0.88, rows0[16]["low"], rows0[16]["high"]), 2)
        add(c0, 3, 16, bp, sp)

    # chase_high: buy 8% above 5-day avg
    if len(rows0) >= 30:
        avg5 = sum(r["close"] for r in rows0[17:22]) / 5
        bp = round(clamp(avg5 * 1.08, rows0[22]["low"], rows0[22]["high"]), 2)
        sp = round(clamp(rows0[28]["close"] * 0.98, rows0[28]["low"], rows0[28]["high"]), 2)
        add(c0, 22, 28, bp, sp)

    # 2-4 normal trades on c1
    if len(rows1) >= 15:
        add(c1, 5, 13)
    for i in range(rng.randint(1, 2)):
        base = 14 + i * 6
        if len(rows1) > base + 5:
            add(c1, base, base + 5)

    return trades


# ── DB insert ─────────────────────────────────────────────────────────────────

async def clear_and_seed(kline_map: dict, news_map: dict[str, list[dict]]) -> None:
    engine = create_async_engine(
        DB_URL,
        echo=False,
        connect_args={"statement_cache_size": 0},
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # ── Ensure stock_news table exists BEFORE DELETE ──────────────────────
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS stock_news (
                id           SERIAL PRIMARY KEY,
                stock_code   VARCHAR(20)  NOT NULL,
                stock_name   VARCHAR(50)  NOT NULL,
                publish_time TIMESTAMP    NOT NULL,
                title        TEXT         NOT NULL,
                summary      TEXT,
                source       VARCHAR(20)  NOT NULL DEFAULT 'finloop',
                created_at   TIMESTAMP    NOT NULL DEFAULT NOW()
            )
        """))
        await session.commit()

        logger.info("Clearing existing data...")
        for tbl in ("reports", "trades", "market_data", "stock_news", "users"):
            await session.execute(text(f"DELETE FROM {tbl}"))
        await session.commit()

        # ── Insert users ──────────────────────────────────────────────────────
        logger.info("Inserting users...")
        for uid, name, ptype in USERS:
            await session.execute(text(
                "INSERT INTO users (id, name, profile_type, created_at) "
                "VALUES (:id, :name, :ptype, NOW())"
            ), {"id": uid, "name": name, "ptype": ptype})
        await session.commit()

        # ── Insert market_data ────────────────────────────────────────────────
        logger.info("Inserting market_data...")
        md_rows = []
        all_codes = [(code, name) for code, name in STOCKS]
        if INDEX_CODE in kline_map:
            all_codes.append((INDEX_CODE, INDEX_NAME))
        for code, name in all_codes:
            for r in kline_map.get(code, []):
                md_rows.append({
                    "stock_code": code, "stock_name": name,
                    "trade_date": r["date"],
                    "open_price":  r["open"],  "high_price": r["high"],
                    "low_price":   r["low"],   "close_price": r["close"],
                    "volume":      r["volume"], "change_pct":  r["change_pct"],
                })
        for i in range(0, len(md_rows), 500):
            batch = md_rows[i:i+500]
            await session.execute(text(
                "INSERT INTO market_data "
                "(stock_code,stock_name,trade_date,open_price,high_price,low_price,close_price,volume,change_pct) "
                "VALUES (:stock_code,:stock_name,:trade_date,:open_price,:high_price,:low_price,:close_price,:volume,:change_pct)"
            ), batch)
        await session.commit()
        logger.info("  → %d market_data rows inserted", len(md_rows))

        # ── Insert stock_news ─────────────────────────────────────────────────
        logger.info("Inserting stock_news...")
        total_news = 0
        for code, name in STOCKS:
            articles = news_map.get(code, [])
            for a in articles:
                await session.execute(text(
                    "INSERT INTO stock_news (stock_code,stock_name,publish_time,title,summary,source) "
                    "VALUES (:stock_code,:stock_name,:publish_time,:title,:summary,:source)"
                ), {
                    "stock_code":   code,
                    "stock_name":   name,
                    "publish_time": a["publish_time"],
                    "title":        a["title"],
                    "summary":      a.get("summary", ""),
                    "source":       a.get("source", "finloop"),
                })
                total_news += 1
        await session.commit()
        logger.info("  → %d stock_news rows inserted", total_news)

        # ── Insert trades ─────────────────────────────────────────────────────
        logger.info("Generating and inserting trades...")
        all_trades = []
        for uid, name, profile in USERS:
            rng = random.Random(uid * 9999)
            if uid == 5:
                trades = generate_zhaoxin_trades(uid, kline_map, rng)
            else:
                trades = generate_trades(uid, profile, kline_map, rng)
            all_trades.extend(trades)
            logger.info("  user %s (%s): %d trade records", name, profile, len(trades))

        for t in all_trades:
            await session.execute(text(
                "INSERT INTO trades "
                "(user_id,stock_code,stock_name,direction,price,quantity,trade_time,pnl,pnl_pct) "
                "VALUES (:user_id,:stock_code,:stock_name,:direction,:price,:quantity,:trade_time,:pnl,:pnl_pct)"
            ), t)
        await session.commit()
        logger.info("  → %d trade records inserted", len(all_trades))

        # ── Fee sanity check ─────────────────────────────────────────────────
        logger.info("=" * 50)
        logger.info("FEE SANITY CHECK (per user):")
        for uid, name, _ in USERS:
            user_trades = [t for t in all_trades if t["user_id"] == uid]
            sells = [t for t in user_trades if t["direction"] == "sell"]
            total_fee = 0.0
            for t in user_trades:
                amt = t["price"] * t["quantity"]
                if t["direction"] == "buy":
                    total_fee += buy_fee(amt)
                else:
                    total_fee += sell_fee(amt)
            pairs = len(sells)
            avg_fee = total_fee / pairs if pairs else 0
            logger.info(
                "  %-6s  %d笔  总手续费=%.0f元  均每笔=%.0f元",
                name, pairs, total_fee, avg_fee
            )
        logger.info("=" * 50)

        # ── News coverage summary ─────────────────────────────────────────────
        logger.info("NEWS COVERAGE SUMMARY:")
        for code, name in STOCKS:
            count = len(news_map.get(code, []))
            logger.info("  %-12s %-8s → %d articles", code, name, count)
        logger.info("=" * 50)

    await engine.dispose()
    logger.info("✅ Supabase seeded successfully.")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    # Init QVeris key pool (for K-line fallback)
    qveris_available = False
    try:
        from app.core.config import get_settings
        from app.services.qveris_client import init_key_pool
        s = get_settings()
        keys = s.all_qveris_keys()
        if keys:
            init_key_pool(keys, s.QVERIS_BASE_URL)
            qveris_available = True
            logger.info("QVeris key pool initialised (%d keys)", len(keys))
    except Exception as e:
        logger.warning("QVeris unavailable: %s — K-line fallback disabled", e)

    # ── Fetch K-line data ─────────────────────────────────────────────────────
    logger.info("=== Fetching K-line data ===")
    kline_map: dict[str, list] = {}
    for code, name in STOCKS:
        rows = await fetch_kline(code, qveris_available)
        kline_map[code] = rows

    # Fetch index K-line (上证指数)
    logger.info("Fetching index K-line: %s", INDEX_CODE)
    index_rows = await fetch_kline(INDEX_CODE, qveris_available)
    kline_map[INDEX_CODE] = index_rows

    # ── Fetch news data ───────────────────────────────────────────────────────
    logger.info("=== Fetching news data ===")
    news_map: dict[str, list] = {}
    for code, name in STOCKS:
        articles: list[dict] = []
        # Primary: finloop-news
        try:
            articles = await fetch_news_finloop(name, code)
        except Exception as e:
            logger.warning("  finloop-news %s failed: %s", name, e)

        if not articles:
            logger.warning("  No in-period news found for %s (%s) — will store 0 articles", name, code)

        news_map[code] = articles

    total = sum(len(v) for v in news_map.values())
    logger.info("Total articles fetched: %d across %d stocks", total, len(STOCKS))

    await clear_and_seed(kline_map, news_map)


async def seed_index_only() -> None:
    """Incremental seed: only insert 000001.SH index K-line into existing DB."""
    qveris_available = False
    try:
        from app.core.config import get_settings
        from app.services.qveris_client import init_key_pool
        s = get_settings()
        keys = s.all_qveris_keys()
        if keys:
            init_key_pool(keys, s.QVERIS_BASE_URL)
            qveris_available = True
    except Exception:
        pass

    logger.info("=== Incremental seed: %s ===", INDEX_CODE)
    rows = await fetch_kline(INDEX_CODE, qveris_available)
    if not rows:
        logger.error("No K-line data fetched for %s — aborting", INDEX_CODE)
        return

    engine = create_async_engine(DB_URL, echo=False,
                                 connect_args={"statement_cache_size": 0})
    async with sessionmaker(engine, class_=AsyncSession)() as session:
        await session.execute(
            text("DELETE FROM market_data WHERE stock_code = :code"),
            {"code": INDEX_CODE},
        )
        md_rows = [
            {
                "stock_code": INDEX_CODE, "stock_name": INDEX_NAME,
                "trade_date": r["date"],
                "open_price":  r["open"],  "high_price": r["high"],
                "low_price":   r["low"],   "close_price": r["close"],
                "volume":      r["volume"], "change_pct":  r["change_pct"],
            }
            for r in rows
        ]
        for i in range(0, len(md_rows), 500):
            batch = md_rows[i:i + 500]
            await session.execute(text(
                "INSERT INTO market_data "
                "(stock_code,stock_name,trade_date,open_price,high_price,low_price,close_price,volume,change_pct) "
                "VALUES (:stock_code,:stock_name,:trade_date,:open_price,:high_price,:low_price,:close_price,:volume,:change_pct)"
            ), batch)
        await session.commit()
        logger.info("  → %d index rows inserted for %s", len(md_rows), INDEX_CODE)

    await engine.dispose()
    logger.info("✅ Index seed completed.")


if __name__ == "__main__":
    if "--index-only" in sys.argv:
        asyncio.run(seed_index_only())
    else:
        asyncio.run(main())
