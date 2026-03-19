// ─── Enums ─────────────────────────────────────────────────────────

export type UserProfileType = 'aggressive' | 'conservative' | 'emotional' | 'balanced'

export type PatternType =
  | 'chase_high'
  | 'early_profit'
  | 'slow_stop_loss'
  | 'hold_too_long'
  | 'fee_drag'

export type TradeDirection = 'buy' | 'sell'

export type ReportStatus = 'pending' | 'generating' | 'completed' | 'failed'

// ─── Interfaces ────────────────────────────────────────────────────

export interface TradeRecord {
  id?: number
  user_id: number
  stock_code: string
  stock_name: string
  direction: TradeDirection
  price: number
  quantity: number
  trade_time: string
  pnl?: number | null
  pnl_pct?: number | null
}

export interface UserProfile {
  user_id: number
  user_name: string
  profile_type: UserProfileType
  trade_count: number
  win_rate: number
  avg_holding_days: number
  total_pnl: number
  avg_pnl_per_trade: number
  max_single_loss: number
  max_single_gain: number
  trade_frequency_per_week: number
}

export interface PatternExampleBase {
  trade_id: number
  buy_trade_id?: number
  sell_trade_id?: number
  stock: string
  buy_date: string
  sell_date: string
  buy_price?: number
  sell_price?: number
  pnl?: number
  [key: string]: unknown
}

export interface PatternResult {
  pattern_type: PatternType
  pattern_name: string
  occurrences: number
  affected_trades: number[]
  total_impact: number
  description: string
  examples: PatternExampleBase[]
  ai_commentary: string
}

export interface DiagnosisResult {
  patterns: PatternResult[]
  primary_issues: string[]
  severity_score: number
  summary: string
  data_warning: 'insufficient' | 'preliminary' | null
}

export interface BacktestTradeDetail {
  trade_id: number
  stock: string
  buy_date: string
  sell_date: string
  buy_price: number
  sell_price: number
  original_pnl: number
  adjusted_pnl: number
}

export interface BacktestScenario {
  name: string
  description: string
  param_change: string
  original_pnl: number
  adjusted_pnl: number
  improvement: number
  improvement_pct: number
  trade_details: BacktestTradeDetail[]
  ai_interpretation: string
}

export interface BacktestResult {
  scenarios: BacktestScenario[]
  best_scenario: string
  max_improvement: number
}

export interface ReportResponse {
  id: number
  user_id: number
  user_name: string
  period_start: string
  period_end: string
  status: ReportStatus
  profile?: UserProfile | null
  patterns?: PatternResult[] | null
  diagnosis?: DiagnosisResult | null
  backtest?: BacktestResult | null
  ai_summary?: string | null
  ai_suggestions?: string | null
  ai_style_description?: string | null
  error_message?: string | null   // traceback when status=failed
  created_at: string
}

export interface ReportListItem {
  id: number
  user_id: number
  user_name: string
  period_start: string
  period_end: string
  status: ReportStatus
  created_at: string
  profile_type?: UserProfileType | null
  total_pnl?: number | null
  win_rate?: number | null
  trade_count?: number | null
}

// ─── Market Data ────────────────────────────────────────────────────

export interface CandleBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface MarketDataResponse {
  stock_code: string
  stock_name: string
  bars: CandleBar[]
}

// ─── Single Trade Review ─────────────────────────────────────────────────────

export interface ClosedTrade {
  buy_trade_id: number
  sell_trade_id: number
  stock_code: string
  stock_name: string
  buy_time: string
  sell_time: string
  buy_price: number
  sell_price: number
  quantity: number
  pnl: number
  pnl_pct: number
  hold_days: number
}

export interface TradeNewsItem {
  publish_time: string
  title: string
  summary: string
  source: string
}

export interface TradeKlineBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  change_pct: number
}

export interface IndexKlineBar {
  date: string
  close: number
  change_pct: number
}

export interface TradeReviewResponse {
  buy_trade_id: number
  sell_trade_id: number
  stock_code: string
  stock_name: string
  buy_time: string
  sell_time: string
  buy_price: number
  sell_price: number
  quantity: number
  pnl: number
  pnl_pct: number
  hold_days: number
  kline: TradeKlineBar[]
  index_kline: IndexKlineBar[]
  news: TradeNewsItem[]
  status: 'generating' | 'completed' | 'failed'
  ai_review?: string | null
  error_message?: string | null
}
