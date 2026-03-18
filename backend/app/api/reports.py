"""Report API routes — generate and retrieve trading analysis reports."""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db, get_async_session
from app.core.auth import get_current_user
from app.models import (
    ReportORM,
    UserORM,
    TradeORM,
    MarketDataORM,
    TradeRecord,
    MarketData,
    ReportRequest,
    ReportResponse,
    ReportListItem,
    ReportStatus,
)
from app.services.profiler import analyze_user_profile
from app.services.pattern import detect_patterns
from app.services.diagnosis import diagnose
from app.services.backtest import run_backtest
from app.services.ai_agent import generate_ai_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["reports"])


# ── Background pipeline ────────────────────────────────────────────────────────

async def _run_pipeline(report_id: int, user_id: int, user_name: str) -> None:
    """Run the full analysis pipeline in the background and update the report."""
    async with get_async_session()() as db:
        report = await db.get(ReportORM, report_id)
        if not report:
            logger.error("[pipeline] report %d not found", report_id)
            return

        try:
            # Fetch trades in period
            # Cast period dates to ensure correct PostgreSQL DATE/TIMESTAMP comparison
            period_start = date.fromisoformat(str(report.period_start))
            period_end = date.fromisoformat(str(report.period_end))

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
            trade_orms = result.scalars().all()
            trades = [TradeRecord.model_validate(t) for t in trade_orms]

            # Fetch market data in period
            stmt_md = (
                select(MarketDataORM)
                .where(
                    MarketDataORM.trade_date >= period_start,
                    MarketDataORM.trade_date <= period_end,
                )
                .order_by(MarketDataORM.trade_date)
            )
            result_md = await db.execute(stmt_md)
            md_orms = result_md.scalars().all()
            market_data = [MarketData.model_validate(m) for m in md_orms]

            # Pipeline
            logger.info("[pipeline:%d] step 1/5 — profiling user %s", report_id, user_name)
            profile = analyze_user_profile(trades, user_id, user_name)
            logger.info("[pipeline:%d] step 2/5 — detecting patterns (%d trades)", report_id, len(trades))
            patterns = detect_patterns(trades, market_data)
            logger.info("[pipeline:%d] step 3/5 — diagnosing (%d patterns)", report_id, len(patterns))
            diagnosis_result = diagnose(profile, patterns)
            logger.info("[pipeline:%d] step 4/5 — backtest", report_id)
            backtest_result = run_backtest(trades, market_data, patterns)
            logger.info("[pipeline:%d] step 5/5 — AI report", report_id)
            ai_result = await generate_ai_report(
                profile, patterns, diagnosis_result, backtest_result
            )

            # Backfill ai_commentary into PatternResult objects
            for p in patterns:
                p.ai_commentary = ai_result.pattern_examples.get(p.pattern_type.value, "")

            # Update report
            report.status = ReportStatus.COMPLETED
            report.profile_data = profile.model_dump(mode="json")
            report.pattern_data = [p.model_dump(mode="json") for p in patterns]
            report.diagnosis_data = diagnosis_result.model_dump(mode="json")
            report.backtest_data = backtest_result.model_dump(mode="json")
            report.ai_summary = ai_result.summary
            report.ai_suggestions = ai_result.suggestions
            report.ai_style_description = ai_result.style_description

            # Also update user profile_type
            user_orm = await db.get(UserORM, user_id)
            if user_orm:
                user_orm.profile_type = profile.profile_type

            await db.commit()
            logger.info("[pipeline] report %d completed", report_id)

        except Exception as e:
            tb = traceback.format_exc()
            logger.error(
                "[pipeline] report %d failed: %s\n%s",
                report_id, e, tb,
                extra={"report_id": report_id, "user_id": user_id},
            )
            report.status = ReportStatus.FAILED
            report.error_message = tb
            await db.commit()


# ── API endpoints ──────────────────────────────────────────────────────────────

@router.post("/generate", response_model=ReportResponse)
async def generate_report(
    req: ReportRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Create report record immediately and run analysis pipeline in background."""

    # Validate user
    user = await db.get(UserORM, req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # Create report record — immediately returns to caller
    report = ReportORM(
        user_id=req.user_id,
        period_start=req.period_start,
        period_end=req.period_end,
        status=ReportStatus.GENERATING,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    # Fire pipeline as background task (non-blocking)
    background_tasks.add_task(_run_pipeline, report.id, user.id, user.name)

    return _report_to_response(report, user.name)


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Fetch a single report by ID."""
    report = await db.get(ReportORM, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    user = await db.get(UserORM, report.user_id)
    return _report_to_response(report, user.name if user else "Unknown")


@router.get("/", response_model=list[ReportListItem])
async def list_reports(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """List all reports."""
    stmt = (
        select(ReportORM, UserORM.name, UserORM.profile_type)
        .join(UserORM, ReportORM.user_id == UserORM.id)
        .order_by(ReportORM.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [
        ReportListItem(
            id=report.id,
            user_id=report.user_id,
            user_name=user_name,
            period_start=report.period_start,
            period_end=report.period_end,
            status=report.status,
            created_at=report.created_at,
            profile_type=profile_type,
            total_pnl=report.profile_data.get("total_pnl") if report.profile_data else None,
            win_rate=report.profile_data.get("win_rate") if report.profile_data else None,
            trade_count=report.profile_data.get("trade_count") if report.profile_data else None,
        )
        for report, user_name, profile_type in rows
    ]


def _report_to_response(report: ReportORM, user_name: str) -> ReportResponse:
    """Convert ORM report + user name to ReportResponse schema."""
    from app.models import (
        UserProfile,
        PatternResult,
        DiagnosisResult,
        BacktestResult,
    )

    profile = UserProfile(**report.profile_data) if report.profile_data else None
    patterns = (
        [PatternResult(**p) for p in report.pattern_data]
        if report.pattern_data
        else None
    )
    diagnosis_obj = (
        DiagnosisResult(**report.diagnosis_data) if report.diagnosis_data else None
    )
    backtest_obj = (
        BacktestResult(**report.backtest_data) if report.backtest_data else None
    )

    return ReportResponse(
        id=report.id,
        user_id=report.user_id,
        user_name=user_name,
        period_start=report.period_start,
        period_end=report.period_end,
        status=report.status,
        profile=profile,
        patterns=patterns,
        diagnosis=diagnosis_obj,
        backtest=backtest_obj,
        ai_summary=report.ai_summary,
        ai_suggestions=report.ai_suggestions,
        ai_style_description=report.ai_style_description,
        error_message=report.error_message,
        created_at=report.created_at,
    )
