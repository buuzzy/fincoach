"""LLM Tool Use Agent — generate AI-powered coaching reports.

Architecture:
  User trade data + analysis results
      → Agent planning (LLM decides which tools to call)
      → Parallel QVeris tool calls (K-lines / market flow / index data)
      → Agent synthesises all context
      → Structured JSON report {summary, suggestions, style_description, pattern_examples}
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.core import get_settings
from app.models import (
    UserProfile,
    PatternResult,
    DiagnosisResult,
    BacktestResult,
)
from app.services.qveris_client import qveris_search, qveris_execute

logger = logging.getLogger(__name__)

# ── Tool Use Agent constants ──────────────────────────────────────────────────

MAX_TOOL_ROUNDS = 5          # guard against infinite tool-call loops
KLINE_WINDOW = 30            # keep only the most recent N rows to save tokens

# QVeris tool IDs that have been validated
_QVERIS_TOOL_IDS = {
    "get_stock_kline": "ths_ifind.history_quotation.v1",
    "get_market_flow": "ths_ifind.money_flow.v1",
    "get_index_kline": "ths_ifind.quotation.v1",
}


# ── Return type ───────────────────────────────────────────────────────────────


@dataclass
class AIReportResult:
    summary: str = ""
    suggestions: str = ""
    style_description: str = ""
    pattern_examples: dict[str, str] = field(default_factory=dict)
    # pattern_examples: {pattern_type_value: commentary_text}


# ── OpenAI function-calling tool definitions ──────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_stock_kline",
            "description": (
                "获取A股个股历史K线数据（开高低收、成交量、换手率）。"
                "用于分析用户持仓股票的价格走势。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codes": {
                        "type": "string",
                        "description": "股票代码，如 600519.SH 或 000001.SZ",
                    },
                    "startdate": {
                        "type": "string",
                        "description": "开始日期，格式 YYYY-MM-DD",
                    },
                    "enddate": {
                        "type": "string",
                        "description": "结束日期，格式 YYYY-MM-DD",
                    },
                    "interval": {
                        "type": "string",
                        "enum": ["D", "W", "M"],
                        "description": "K线周期：D=日线，W=周线，M=月线",
                        "default": "D",
                    },
                },
                "required": ["codes", "startdate", "enddate"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_flow",
            "description": (
                "获取个股、行业板块或大盘的资金流向数据（主力净流入/流出）。"
                "用于判断资金面的支撑或压力。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["stock", "sector", "market"],
                        "description": "查询范围：stock=个股，sector=板块，market=大盘",
                    },
                    "codes": {
                        "type": "string",
                        "description": "证券代码（scope=market 时可留空）",
                    },
                    "startdate": {
                        "type": "string",
                        "description": "开始日期，格式 YYYY-MM-DD",
                    },
                    "enddate": {
                        "type": "string",
                        "description": "结束日期，格式 YYYY-MM-DD",
                    },
                },
                "required": ["scope", "startdate", "enddate"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_index_kline",
            "description": (
                "获取大盘指数K线数据，如上证指数（000001.SH）、"
                "沪深300（000300.SH）等。用于分析市场整体走势背景。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codes": {
                        "type": "string",
                        "description": "指数代码，如 000001.SH 或 000300.SH",
                    },
                    "startdate": {
                        "type": "string",
                        "description": "开始日期，格式 YYYY-MM-DD",
                    },
                    "enddate": {
                        "type": "string",
                        "description": "结束日期，格式 YYYY-MM-DD",
                    },
                },
                "required": ["codes", "startdate", "enddate"],
            },
        },
    },
]


# ── QVeris tool dispatch ───────────────────────────────────────────────────────


async def _call_qveris(
    tool_name: str,
    args: dict[str, Any],
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """Map an LLM tool call to a QVeris search+execute sequence.

    Returns a result dict. On failure returns {"error": "<message>"}.
    """
    qveris_tool_id = _QVERIS_TOOL_IDS.get(tool_name)
    if not qveris_tool_id:
        return {"error": f"Unknown tool: {tool_name}"}

    # Build natural-language search query to resolve the tool
    query_map = {
        "get_stock_kline": f"A股历史K线 {args.get('codes', '')}",
        "get_market_flow": f"资金流向 {args.get('scope', '')} {args.get('codes', '')}",
        "get_index_kline": f"大盘指数K线 {args.get('codes', '')}",
    }
    query = query_map[tool_name]

    try:
        tool_id, search_id = await qveris_search(
            query=query,
            api_key=api_key,
            base_url=base_url,
        )
    except Exception as exc:
        logger.warning("[QVeris] search failed tool=%s: %s", tool_name, exc)
        return {"error": f"QVeris search failed: {exc}"}

    # Build execution params
    params: dict[str, Any] = dict(args)
    # interval defaults to "D" for kline tools
    if tool_name in ("get_stock_kline", "get_index_kline"):
        params.setdefault("interval", "D")

    try:
        result = await qveris_execute(
            tool_id=tool_id,
            search_id=search_id,
            params=params,
            api_key=api_key,
            base_url=base_url,
        )
    except Exception as exc:
        logger.warning("[QVeris] execute failed tool=%s: %s", tool_name, exc)
        return {"error": f"QVeris execute failed: {exc}"}

    # Truncate large data arrays to avoid overflowing context window
    result = _truncate_data(result)
    return result


def _truncate_data(data: Any, max_rows: int = KLINE_WINDOW) -> Any:
    """Recursively truncate list values to the most recent *max_rows* entries."""
    if isinstance(data, list):
        truncated = data[-max_rows:]
        return truncated
    if isinstance(data, dict):
        return {k: _truncate_data(v, max_rows) for k, v in data.items()}
    return data


# ── Prompt helpers ─────────────────────────────────────────────────────────────


def _build_system_prompt() -> str:
    return (
        "你是A股交易教练，可以调用工具获取实时行情数据辅助分析。\n\n"
        "输出严格 JSON：\n"
        '{\n'
        '  "summary": "本期交易总结（200字内，客观陈述数据与表现）",\n'
        '  "suggestions": "改进建议（200字内，具体可操作）",\n'
        '  "style_description": "交易行为描述（100字内，描述行为如持仓时长/频率，禁用激进型等人格标签）",\n'
        '  "pattern_examples": {\n'
        '    "<pattern_type>": "该pattern典型案例的点评（80字内，结合具体股票和数据）"\n'
        '  }\n'
        '}\n'
        'pattern_examples 仅包含本次报告检测到的 pattern。\n'
        "style_description 示例：'平均持仓3天，周均操作5次，多数盈利交易在3天内完成，亏损交易持仓明显偏长。'"
    )


def _build_user_message(
    profile: UserProfile,
    patterns: list[PatternResult],
    diagnosis: DiagnosisResult,
    backtest: BacktestResult,
    period_start: str,
    period_end: str,
    stock_codes: list[str],
) -> str:
    """Build the initial user message with structured trade analysis summary."""

    # Build pattern summary with top example for each pattern
    pattern_summaries: list[str] = []
    for p in patterns:
        summary_line = f"- {p.pattern_name}（{p.occurrences}次，影响{p.total_impact:,.2f}元）"
        if p.examples:
            ex = p.examples[0]
            stock = ex.get("stock", "")
            buy_date = ex.get("buy_date", "")
            sell_date = ex.get("sell_date", "")
            pnl = ex.get("pnl", ex.get("missed_gain", ""))
            summary_line += f"\n  典型案例：{stock}，买入{buy_date}，卖出{sell_date}，盈亏{pnl}"
        pattern_summaries.append(summary_line)

    pattern_text = "\n".join(pattern_summaries) if pattern_summaries else "（无检测到的模式）"
    pattern_types = [p.pattern_type.value for p in patterns]

    codes_str = "、".join(stock_codes) if stock_codes else "（无具体股票代码）"

    return f"""请分析以下用户交易数据，生成个性化复盘报告。

## 分析期间
{period_start} 至 {period_end}

## 涉及股票代码
{codes_str}

## 用户画像
- 用户：{profile.user_name}
- 交易笔数：{profile.trade_count}
- 胜率：{profile.win_rate:.1%}
- 平均持仓天数：{profile.avg_holding_days:.1f}天
- 总盈亏：{profile.total_pnl:,.2f}元
- 单笔最大亏损：{profile.max_single_loss:,.2f}元
- 单笔最大盈利：{profile.max_single_gain:,.2f}元
- 每周交易频率：{profile.trade_frequency_per_week:.1f}次

## 检测到的交易模式（含典型案例）
{pattern_text}

## 诊断结果
- 严重程度评分：{diagnosis.severity_score}/100
- 主要问题：{'、'.join(diagnosis.primary_issues)}
- 摘要：{diagnosis.summary}

## 本次检测到的 pattern 类型（用于 pattern_examples key）
{json.dumps(pattern_types, ensure_ascii=False)}

请先通过工具获取相关行情数据（建议至少查询大盘指数走势），再综合以上数据生成报告。
最终以JSON格式返回，pattern_examples 中仅需包含以上列出的 pattern 类型。"""


def _extract_stock_codes(
    profile: UserProfile,
    patterns: list[PatternResult],
) -> list[str]:
    """Best-effort extraction of stock codes from available data."""
    codes: list[str] = []
    # UserProfile may carry stock codes in various attributes; try common ones
    for attr in ("stock_codes", "stocks", "holdings"):
        val = getattr(profile, attr, None)
        if isinstance(val, list):
            codes.extend(str(v) for v in val)
        elif isinstance(val, str) and val:
            codes.append(val)

    # Patterns may also reference stock codes
    for p in patterns:
        for attr in ("stock_code", "code", "symbol"):
            val = getattr(p, attr, None)
            if val and isinstance(val, str):
                codes.append(val)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _extract_date_range(
    profile: UserProfile,
    backtest: BacktestResult,
) -> tuple[str, str]:
    """Return (period_start, period_end) strings in YYYY-MM-DD format."""
    # Prefer explicit date range attrs on profile/backtest if they exist
    start = getattr(profile, "period_start", None) or getattr(
        backtest, "period_start", None
    )
    end = getattr(profile, "period_end", None) or getattr(
        backtest, "period_end", None
    )

    if start and end:
        # Normalise to string
        return str(start)[:10], str(end)[:10]

    # Fall back to a sensible default: last 3 months
    from datetime import date, timedelta

    today = date.today()
    three_months_ago = today - timedelta(days=90)
    return three_months_ago.isoformat(), today.isoformat()


# ── JSON parsing helper ────────────────────────────────────────────────────────


def _parse_json_response(content: str) -> AIReportResult:
    """Extract AIReportResult from an LLM JSON response string."""
    cleaned = content.strip()

    # Strip markdown code fences
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    # Find the outermost JSON object
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        if start != -1:
            cleaned = cleaned[start:]
    if not cleaned.endswith("}"):
        end = cleaned.rfind("}")
        if end != -1:
            cleaned = cleaned[: end + 1]

    data = json.loads(cleaned)
    return AIReportResult(
        summary=data.get("summary", ""),
        suggestions=data.get("suggestions", ""),
        style_description=data.get("style_description", ""),
        pattern_examples=data.get("pattern_examples", {}),
    )


# ── Fallback (template-based) ──────────────────────────────────────────────────


def _fallback_report(
    profile: UserProfile,
    patterns: list[PatternResult],
    diagnosis: DiagnosisResult,
    backtest: BacktestResult,
) -> AIReportResult:
    """Template-based fallback when LLM is unavailable."""

    summary = (
        f"用户 {profile.user_name} 在分析期间共完成{profile.trade_count}笔交易，"
        f"胜率{profile.win_rate:.1%}，总盈亏{profile.total_pnl:,.2f}元。"
        f"平均持仓{profile.avg_holding_days:.1f}天，每周交易{profile.trade_frequency_per_week:.1f}次。"
        f"诊断严重程度评分：{diagnosis.severity_score}/100。"
    )

    style_description = (
        f"平均持仓{profile.avg_holding_days:.1f}天，"
        f"周均操作{profile.trade_frequency_per_week:.1f}次，"
        f"胜率{profile.win_rate:.1%}，总计{profile.trade_count}笔交易。"
    )

    suggestion_lines: list[str] = []
    for p in diagnosis.patterns[:5]:
        ptype = p.pattern_type.value
        if ptype == "chase_high":
            suggestion_lines.append(
                "1. 设置买入纪律：避免在股价高于5日均线5%以上时追高买入，等待回调后再入场。"
            )
        elif ptype == "early_profit":
            suggestion_lines.append(
                "2. 优化止盈策略：当盈利达到目标时，可采用移动止盈而非立即全部卖出。"
            )
        elif ptype == "slow_stop_loss":
            suggestion_lines.append(
                "3. 严格止损纪律：建议将止损线设置在-6%，亏损达到止损线时果断执行。"
            )
        elif ptype == "over_trading":
            suggestion_lines.append(
                "4. 控制交易频率：建议每周交易不超过3次，减少手续费和情绪干扰。"
            )
        elif ptype == "hold_too_long":
            suggestion_lines.append(
                "5. 设置最长持仓期限：对于亏损持仓，建议在15个交易日内进行止损评估。"
            )

    if not suggestion_lines:
        suggestion_lines.append("继续保持当前的交易纪律，注意风险控制。")

    suggestions = "\n".join(suggestion_lines)

    if backtest.scenarios:
        suggestions += (
            f"\n\n回测显示，最优方案「{backtest.best_scenario}」"
            f"可改善盈亏{backtest.max_improvement:,.2f}元。"
        )

    # Generate fallback pattern examples
    pattern_examples: dict[str, str] = {}
    for p in patterns:
        if p.examples:
            ex = p.examples[0]
            stock = ex.get("stock", "")
            pnl = ex.get("pnl", ex.get("missed_gain", 0))
            pattern_examples[p.pattern_type.value] = (
                f"{stock}，影响金额{pnl:,.2f}元，为该模式典型案例。"
                if isinstance(pnl, (int, float)) else
                f"{stock}，为该模式典型案例。"
            )

    return AIReportResult(
        summary=summary,
        suggestions=suggestions,
        style_description=style_description,
        pattern_examples=pattern_examples,
    )


# ── Main entry point ───────────────────────────────────────────────────────────


async def generate_ai_report(
    profile: UserProfile,
    patterns: list[PatternResult],
    diagnosis: DiagnosisResult,
    backtest: BacktestResult,
) -> AIReportResult:
    """Generate coaching report using a Tool Use Agent.

    Returns AIReportResult with summary, suggestions, style_description, pattern_examples.
    """
    settings = get_settings()

    if not settings.LLM_API_KEY:
        logger.info("[AI Agent] No LLM_API_KEY, using fallback template.")
        return _fallback_report(profile, patterns, diagnosis, backtest)

    try:
        return await _run_tool_use_agent(profile, patterns, diagnosis, backtest)
    except Exception as exc:
        import traceback

        traceback.print_exc()
        logger.error("[AI Agent] Tool Use Agent failed: %s — falling back.", exc)
        return _fallback_report(profile, patterns, diagnosis, backtest)


async def _run_tool_use_agent(
    profile: UserProfile,
    patterns: list[PatternResult],
    diagnosis: DiagnosisResult,
    backtest: BacktestResult,
) -> AIReportResult:
    """Core Tool Use Agent loop."""
    from openai import AsyncOpenAI

    settings = get_settings()
    client = AsyncOpenAI(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
    )

    period_start, period_end = _extract_date_range(profile, backtest)
    stock_codes = _extract_stock_codes(profile, patterns)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _build_system_prompt()},
        {
            "role": "user",
            "content": _build_user_message(
                profile, patterns, diagnosis, backtest,
                period_start, period_end, stock_codes,
            ),
        },
    ]

    # Whether QVeris is available for tool execution
    qveris_enabled = bool(settings.QVERIS_API_KEY)
    if not qveris_enabled:
        logger.info(
            "[AI Agent] QVERIS_API_KEY not set — tool calls will return stub errors."
        )

    # ── Agent loop ─────────────────────────────────────────────────────────────
    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        logger.info("[AI Agent] Round %d — calling LLM", round_num)

        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=4000,
        )

        choice = response.choices[0]
        finish_reason = choice.finish_reason
        assistant_message = choice.message

        # Add assistant turn to message history
        messages.append(assistant_message.model_dump(exclude_none=True))

        logger.info(
            "[AI Agent] Round %d finish_reason=%s tool_calls=%s",
            round_num,
            finish_reason,
            len(assistant_message.tool_calls or []),
        )

        if finish_reason == "stop" or not assistant_message.tool_calls:
            # Agent is done — extract final answer
            content = assistant_message.content or ""
            try:
                return _parse_json_response(content)
            except (json.JSONDecodeError, KeyError) as parse_err:
                logger.warning(
                    "[AI Agent] JSON parse failed: %s — returning raw content", parse_err
                )
                return AIReportResult(summary=content, suggestions="")

        # ── Execute tool calls in parallel ─────────────────────────────────────
        tool_calls = assistant_message.tool_calls

        async def _execute_one(tc: Any) -> tuple[str, dict[str, Any]]:
            """Return (tool_call_id, result_dict)."""
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            tool_name = tc.function.name
            logger.info(
                "[AI Agent] Executing tool=%s args=%s", tool_name, args
            )

            if not qveris_enabled:
                result = {
                    "error": "QVERIS_API_KEY not configured — no live data available."
                }
            else:
                result = await _call_qveris(
                    tool_name=tool_name,
                    args=args,
                    api_key=settings.QVERIS_API_KEY,
                    base_url=settings.QVERIS_BASE_URL,
                )

            return tc.id, result

        results = await asyncio.gather(*[_execute_one(tc) for tc in tool_calls])

        # Append one tool result message per call
        for call_id, result_data in results:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result_data, ensure_ascii=False),
                }
            )

    # If we exhausted MAX_TOOL_ROUNDS without a "stop", do one final call
    # without tools to force a text response.
    logger.warning(
        "[AI Agent] Reached MAX_TOOL_ROUNDS=%d — forcing final answer.", MAX_TOOL_ROUNDS
    )
    messages.append(
        {
            "role": "user",
            "content": (
                "已达到工具调用上限，请根据已获取的所有数据立即生成最终报告，"
                '以JSON格式返回：{"summary": "...", "suggestions": "...", '
                '"style_description": "...", "pattern_examples": {...}}。'
            ),
        }
    )
    final_response = await client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=4000,
    )
    content = final_response.choices[0].message.content or ""
    try:
        return _parse_json_response(content)
    except (json.JSONDecodeError, KeyError) as parse_err:
        logger.warning(
            "[AI Agent] Final JSON parse failed: %s — returning raw content", parse_err
        )
        return AIReportResult(summary=content, suggestions="")
