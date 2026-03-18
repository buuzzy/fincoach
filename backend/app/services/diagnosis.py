"""Problem diagnosis — ranks patterns and produces a severity score."""

from __future__ import annotations

from app.models import (
    UserProfile,
    PatternResult,
    DiagnosisResult,
)

_PATTERN_LABELS: dict[str, str] = {
    "chase_high": "追高买入",
    "early_profit": "止盈过早",
    "slow_stop_loss": "止损过慢",
    "over_trading": "频繁交易",
    "hold_too_long": "持仓过久",
}


def diagnose(
    profile: UserProfile,
    patterns: list[PatternResult],
) -> DiagnosisResult:
    """Produce a diagnosis from the user profile and detected patterns."""

    if not patterns:
        return DiagnosisResult(
            patterns=[],
            primary_issues=[],
            severity_score=0.0,
            summary=f"用户 {profile.user_name} 的交易记录中未发现明显的不良交易模式，继续保持！",
            data_warning=(
                "insufficient" if profile.trade_count < 10
                else ("preliminary" if profile.trade_count < 30 else None)
            ),
        )

    # Rank by absolute total_impact (worst / most negative first)
    ranked = sorted(patterns, key=lambda p: p.total_impact)

    # Primary issues — top 2-3 most impactful
    primary_issues: list[str] = []
    for p in ranked[:3]:
        label = _PATTERN_LABELS.get(p.pattern_type.value, p.pattern_name)
        primary_issues.append(label)

    # --- severity_score (0-100) ---
    # Base: 20 pts per distinct pattern (max 5 patterns → 100)
    pattern_count_score = min(len(patterns) * 20, 60)

    # Impact score: scale absolute impact relative to total_pnl
    total_negative_impact = sum(
        abs(p.total_impact) for p in patterns if p.total_impact < 0
    )
    if profile.total_pnl != 0:
        impact_ratio = total_negative_impact / max(abs(profile.total_pnl), 1)
    else:
        impact_ratio = 1.0 if total_negative_impact > 0 else 0.0
    impact_score = min(impact_ratio * 40, 40)

    severity_score = round(min(pattern_count_score + impact_score, 100), 1)

    # --- summary text ---
    issue_str = "、".join(primary_issues)
    summary_parts = [
        f"用户 {profile.user_name}（{profile.profile_type.value} 类型）",
        f"在分析期间共完成 {profile.trade_count} 笔交易，",
        f"胜率 {profile.win_rate:.1%}，总盈亏 {profile.total_pnl:,.2f} 元。",
        f"主要问题：{issue_str}。",
        f"严重程度评分：{severity_score}/100。",
    ]
    summary = "".join(summary_parts)

    return DiagnosisResult(
        patterns=ranked,
        primary_issues=primary_issues,
        severity_score=severity_score,
        summary=summary,
        data_warning=(
            "insufficient" if profile.trade_count < 10
            else ("preliminary" if profile.trade_count < 30 else None)
        ),
    )
