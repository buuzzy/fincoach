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
    BacktestScenarioConfig,
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
    backtest_interpretations: dict[str, str] = field(default_factory=dict)
    # pattern_examples: {pattern_type_value: commentary_text}
    # backtest_interpretations: {scenario_name: interpretation_text}


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
        "重要：所有输出文本中，请用「该账户」指代交易者，禁止出现任何人名。\n\n"
        "输出格式要求（极其重要）：\n"
        "1. 只输出一个 JSON 对象，不要在 JSON 前后添加任何文字、说明或引导语\n"
        "2. 每个字段的值必须是纯文本字符串，禁止包含 Markdown 格式"
        "（如 ** # - 等），禁止嵌套 JSON\n"
        "3. summary 和 suggestions 中用序号分段（①②③ 或 1. 2. 3.），换行分隔\n\n"
        "JSON 结构：\n"
        '{\n'
        '  "summary": "本期交易总结（200字内，客观陈述数据与表现，用①②③分段）",\n'
        '  "suggestions": "改进建议（200字内，具体可操作，用1. 2. 3.分条）",\n'
        '  "style_description": "交易行为描述（100字内，描述持仓时长/频率等行为特征，禁用激进型等人格标签）",\n'
        '  "pattern_examples": {\n'
        '    "<pattern_type>": "该pattern典型案例的点评（80字内，结合具体股票和数据）"\n'
        '  },\n'
        '  "backtest_interpretations": {\n'
        '    "<scenario_name>": "对该回测场景结果的个性化解读（80字内）"\n'
        '  }\n'
        '}\n\n'
        "pattern_examples 仅包含本次报告检测到的 pattern。\n"
        "backtest_interpretations 仅包含本次报告运行的回测场景名称作为 key。"
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

    # Build backtest scenario summary
    scenario_summaries: list[str] = []
    scenario_names: list[str] = []
    for s in backtest.scenarios:
        scenario_names.append(s.name)
        scenario_summaries.append(
            f"- {s.name}：原始盈亏{s.original_pnl:,.2f}元 → 优化后{s.adjusted_pnl:,.2f}元"
            f"，改善{s.improvement:+,.2f}元（{s.improvement_pct:+.1f}%）\n"
            f"  设计理由：{s.description}"
        )
    backtest_text = "\n".join(scenario_summaries) if scenario_summaries else "（无回测场景）"

    codes_str = "、".join(stock_codes) if stock_codes else "（无具体股票代码）"

    return f"""请分析以下交易账户数据，生成个性化复盘报告。所有文本中请用「该账户」指代交易者，禁止出现任何人名。

## 分析期间
{period_start} 至 {period_end}

## 涉及股票代码
{codes_str}

## 账户画像
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

## 回测场景结果（LLM 专项设计）
{backtest_text}

## 本次检测到的 pattern 类型（用于 pattern_examples key）
{json.dumps(pattern_types, ensure_ascii=False)}

## 本次回测场景名称（用于 backtest_interpretations key，请原样使用）
{json.dumps(scenario_names, ensure_ascii=False)}

请先通过工具获取相关行情数据（建议至少查询大盘指数走势），再综合以上数据生成报告。
最终以JSON格式返回，pattern_examples 中仅需包含以上列出的 pattern 类型，backtest_interpretations 中仅需包含以上列出的场景名称。"""


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


def _clean_display_text(text: str) -> str:
    """Strip JSON, code fences, markdown formatting from LLM output text."""
    import re

    s = text.strip()
    # Remove code fences: ```json ... ``` or ``` ... ```
    s = re.sub(r'```[\w]*\n?', '', s)
    # Remove markdown headers
    s = re.sub(r'#{1,6}\s?', '', s)
    # Remove bold / italic markers
    s = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', s)
    # Remove markdown list prefixes
    s = re.sub(r'^[-*]\s', '', s, flags=re.MULTILINE)
    # Remove inline JSON-like fragments: {"key": "value", ...}
    s = re.sub(r'\{[^{}]*\}', '', s)
    # Collapse multiple blank lines
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


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
        summary=_clean_display_text(data.get("summary", "")),
        suggestions=_clean_display_text(data.get("suggestions", "")),
        style_description=_clean_display_text(data.get("style_description", "")),
        pattern_examples={
            k: _clean_display_text(v) for k, v in data.get("pattern_examples", {}).items()
        },
        backtest_interpretations={
            k: _clean_display_text(v) for k, v in data.get("backtest_interpretations", {}).items()
        },
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
        f"该账户在分析期间共完成{profile.trade_count}笔交易，"
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
        elif ptype == "fee_drag":
            suggestion_lines.append(
                "4. 降低短线交易频率：部分短线交易的盈亏未能覆盖手续费成本，建议减少持仓不足5天的操作。"
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


# ── LLM Call 1: Design backtest scenarios ─────────────────────────────────────

_SCENARIO_DESIGN_SYSTEM = (
    "你是A股量化策略分析师，根据账户特征为其量身设计2-3个回测策略场景。\n\n"
    "【A股市场背景】\n"
    "- 交易品种：沪深A股（含主板、创业板、科创板），非期货、非虚拟货币\n"
    "- 交易制度：T+1（当日买入次日才能卖出），无日内做空\n"
    "- 手续费结构：\n"
    "    买入：成交额 × 0.03%（佣金，部分券商更低）\n"
    "    卖出：成交额 × 0.03%（佣金）+ 成交额 × 0.10%（印花税，仅卖出收取）\n"
    "    一个完整来回最低成本约为成交额的 0.16%\n"
    "- 短线交易参考定义：持仓 < 5个交易日通常被视为短线操作\n"
    "- 分批建仓/分批止盈是合理行为，不应被视为频繁交易问题\n\n"
    "【可选策略类型及参数】\n"
    "  stop_loss_tighten:     params.threshold_pct（止损线，如 -4 到 -7，默认-6）\n"
    "  profit_hold_extend:    params.hold_days（延长持有天数，如 3 到 15，默认5）\n"
    "  chase_high_avoid:      params.ma_multiplier（追高阈值，如 1.02 到 1.06，默认1.03）\n"
    "  trade_frequency_limit: params.max_per_week（每周最多交易次数，如 2 到 5，默认3）\n"
    "  hold_duration_limit:   params.max_days（最长持仓天数，如 10 到 30，默认15）\n"
    "  fee_drag_reduce:       params.max_holding_days（短线阈值天数，如 2 到 7，默认5）\n"
    "                         params.fee_cover_multiplier（盈亏须覆盖手续费的倍数，如 1.5 到 3，默认2）\n\n"
    "【选择原则】\n"
    "  - 只选择与该账户最相关的2-3个类型\n"
    "  - 参数要根据账户实际数据个性化：\n"
    "      * 账户平均持仓天数影响 max_holding_days（均值10天→阈值3天，均值3天→阈值1天）\n"
    "      * 账户平均亏损幅度影响 threshold_pct（平均亏损-12%→止损设-7%）\n"
    "      * 若检测到 fee_drag 模式，优先推荐 fee_drag_reduce 场景\n"
    "  - llm_rationale 要引用账户具体数据说明为何选择该策略（50字内），禁止出现人名\n"
    "  - name 要简洁直观，体现个性化参数，如「规避低效短线（持仓<3天）」\n\n"
    "严格输出 JSON，用「该账户」指代，禁止出现任何人名：\n"
    '{"scenarios": [{"type": "...", "name": "...", "llm_rationale": "...", "params": {...}}, ...]}'
)


async def design_backtest_scenarios(
    profile: UserProfile,
    patterns: list[PatternResult],
    diagnosis: DiagnosisResult,
) -> list[BacktestScenarioConfig]:
    """LLM Call 1: design personalised backtest scenario configs for this account."""
    settings = get_settings()

    if not settings.LLM_API_KEY:
        logger.info("[AI Agent] No LLM_API_KEY, using default backtest scenarios.")
        return []

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
        )

        # Build a concise account summary for scenario design
        pattern_summary = ", ".join(
            f"{p.pattern_name}×{p.occurrences}" for p in patterns
        ) or "无明显模式"

        user_msg = (
            f"账户特征：\n"
            f"- 交易笔数：{profile.trade_count}，胜率：{profile.win_rate:.1%}\n"
            f"- 总盈亏：{profile.total_pnl:,.2f}元，平均持仓：{profile.avg_holding_days:.1f}天\n"
            f"- 单笔最大亏损：{profile.max_single_loss:,.2f}元，单笔最大盈利：{profile.max_single_gain:,.2f}元\n"
            f"- 每周交易频率：{profile.trade_frequency_per_week:.1f}次\n"
            f"- 检测到的模式：{pattern_summary}\n"
            f"- 主要诊断问题：{'、'.join(diagnosis.primary_issues)}\n\n"
            f"注意：该账户在沪深A股市场交易，T+1制度，手续费结构为买入0.03%+卖出0.13%（含印花税）。\n"
            f"请为该账户设计2-3个最有针对性的回测策略场景，以JSON输出。"
        )

        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": _SCENARIO_DESIGN_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.5,
            max_tokens=800,
        )

        content = response.choices[0].message.content or ""
        # Strip markdown fences
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            if start != -1:
                cleaned = cleaned[start:]

        data = json.loads(cleaned)
        configs = [
            BacktestScenarioConfig(
                type=s["type"],
                name=s.get("name", s["type"]),
                llm_rationale=s.get("llm_rationale", ""),
                params=s.get("params", {}),
            )
            for s in data.get("scenarios", [])
            if s.get("type")
        ]
        logger.info("[AI Agent] LLM designed %d backtest scenarios", len(configs))
        return configs

    except Exception as exc:
        logger.warning("[AI Agent] design_backtest_scenarios failed: %s — using defaults", exc)
        return []


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
            content = assistant_message.content or ""
            try:
                return _parse_json_response(content)
            except (json.JSONDecodeError, KeyError) as parse_err:
                logger.warning(
                    "[AI Agent] JSON parse failed: %s — cleaning raw content", parse_err
                )
                return AIReportResult(
                    summary=_clean_display_text(content),
                    suggestions="",
                )

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
                '"style_description": "...", "pattern_examples": {...}, "backtest_interpretations": {...}}。'
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
            "[AI Agent] Final JSON parse failed: %s — cleaning raw content", parse_err
        )
        return AIReportResult(
            summary=_clean_display_text(content),
            suggestions="",
        )
