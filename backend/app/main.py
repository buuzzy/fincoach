"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, text

# ── Logging must be configured before any other app imports emit logs ─────────
from app.core.logging_config import setup_logging
setup_logging()

from app.core import init_db, get_async_session
from app.models import UserORM
from app.api.auth import router as auth_router
from app.api.reports import router as reports_router
from app.api.users import router as users_router
from app.api.market import router as market_router
from app.api.trades import router as trades_router

logger = logging.getLogger(__name__)


async def _seed_if_needed(force: bool = False) -> None:
    """Seed (or re-seed) mock data in the background.

    If *force* is True the market_data, trades and reports tables are wiped
    first so a fresh seed with real K-line data is always performed.
    """
    async with get_async_session()() as session:
        if force:
            logger.info("[seed] FORCE_RESEED=true — truncating all data tables...")
            for tbl in ("reports", "trades", "market_data", "users"):
                await session.execute(text(f"DELETE FROM {tbl}"))
            await session.commit()

        result = await session.execute(select(func.count(UserORM.id)))
        user_count = result.scalar() or 0

    if force or user_count == 0:
        logger.info("[seed] Seeding database with real K-line data...")
        from app.data.generate_mock import seed_database
        await seed_database()
    else:
        logger.info("[seed] Database already populated (%d users) — skipping seed.", user_count)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, init QVeris KeyPool, then seed as a background task."""
    try:
        await init_db()
    except Exception as exc:
        logger.error("[startup] init_db failed: %s — continuing anyway", exc)

    force_reseed = False
    try:
        from app.core.config import get_settings
        from app.services.qveris_client import init_key_pool

        settings_obj = get_settings()
        keys = settings_obj.all_qveris_keys()
        if keys:
            init_key_pool(keys, settings_obj.QVERIS_BASE_URL)
        else:
            logger.warning("[startup] No QVERIS_API_KEY configured — QVeris tools disabled.")
        force_reseed = settings_obj.FORCE_RESEED
    except Exception as exc:
        logger.error("[startup] Failed to init QVeris KeyPool: %s", exc)

    # Fire-and-forget: use asyncio.ensure_future (safe in all Python 3.10+ async contexts)
    try:
        asyncio.ensure_future(_seed_if_needed(force=force_reseed))
    except Exception as exc:
        logger.error("[startup] Failed to schedule seed task: %s", exc)

    yield


app = FastAPI(
    title="TraderCoach",
    description="AI-powered trading behaviour analysis and coaching for A-share retail investors",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Global exception handler — catches unhandled 500s ────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    tb = traceback.format_exc()
    logger.error(
        "Unhandled exception on %s %s: %s\n%s",
        request.method,
        request.url.path,
        exc,
        tb,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试", "error": str(exc)},
    )

# CORS — allow Cloudflare Pages + localhost dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://fincoach-aee.pages.dev",
        "http://localhost:5173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)
app.include_router(reports_router)
app.include_router(users_router)
app.include_router(market_router)
app.include_router(trades_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "TraderCoach"}
