import axios, { AxiosError } from 'axios'
import type {
  ReportResponse,
  ReportListItem,
  MarketDataResponse,
  ClosedTrade,
  TradeReviewResponse,
} from '../types'

// ── 错误类型 ────────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code: 'network' | 'timeout' | 'server' | 'not_found' | 'client' | 'unauthorized',
    public readonly status?: number,
    public readonly detail?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** 把 axios error 转换为语义化的 ApiError */
function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err
  if (!axios.isAxiosError(err)) {
    return new ApiError('未知错误，请重试', 'client')
  }

  const axiosErr = err as AxiosError<{ detail?: string; error?: string }>
  const detail = axiosErr.response?.data?.detail ?? axiosErr.response?.data?.error

  if (axiosErr.code === 'ECONNABORTED' || axiosErr.message?.includes('timeout')) {
    return new ApiError('请求超时，请检查网络后重试', 'timeout', undefined, detail)
  }
  if (!axiosErr.response) {
    return new ApiError('无法连接到服务器，请检查后端服务是否运行', 'network', undefined, detail)
  }

  const status = axiosErr.response.status
  if (status === 401) return new ApiError('账号或密码错误', 'unauthorized', status, detail)
  if (status === 404) return new ApiError(detail ?? '资源不存在', 'not_found', status, detail)
  if (status >= 500) return new ApiError(detail ?? '服务器内部错误，请稍后重试', 'server', status, detail)
  if (status >= 400) return new ApiError(detail ?? '请求参数有误', 'client', status, detail)

  return new ApiError('请求失败，请重试', 'client', status, detail)
}

// ── Axios 实例 ───────────────────────────────────────────────────────────────

// 生产环境：VITE_API_BASE_URL=https://api.trademind.nakocai.com
// 开发环境：空字符串，走 vite proxy → localhost:8000
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '') + '/api'

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 60000,
})

api.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(toApiError(error)),
)

// ─── Auth ───────────────────────────────────────────────────────────

export interface LoginPayload {
  username: string
  password: string
}

export async function login(payload: LoginPayload): Promise<void> {
  await api.post('/auth/login', payload)
}

// ─── Reports ───────────────────────────────────────────────────────

export interface GenerateReportPayload {
  user_id: number
  period_start: string // YYYY-MM-DD
  period_end: string   // YYYY-MM-DD
}

export async function generateReport(
  payload: GenerateReportPayload,
): Promise<ReportResponse> {
  const { data } = await api.post<ReportResponse>('/reports/generate', payload)
  return data
}

export async function getReport(id: number): Promise<ReportResponse> {
  const { data } = await api.get<ReportResponse>(`/reports/${id}`)
  return data
}

export async function getReports(): Promise<ReportListItem[]> {
  const { data } = await api.get<ReportListItem[]>('/reports/')
  return data
}

// ─── Market Data ────────────────────────────────────────────────────

export async function getMarketData(
  stockCode: string,
  startDate: string,
  endDate: string,
): Promise<MarketDataResponse> {
  const { data } = await api.get<MarketDataResponse>(
    `/market-data/${stockCode}`,
    { params: { start: startDate, end: endDate } },
  )
  return data
}

// ─── Trades ─────────────────────────────────────────────────────────

export async function getClosedTrades(
  userId: number,
  start: string,
  end: string,
): Promise<ClosedTrade[]> {
  const { data } = await api.get<ClosedTrade[]>(`/trades/${userId}/closed`, {
    params: { start, end },
  })
  return data
}

export async function getTradeReview(
  buyTradeId: number,
  sellTradeId: number,
): Promise<TradeReviewResponse> {
  const { data } = await api.get<TradeReviewResponse>(
    `/trades/review/${buyTradeId}/${sellTradeId}`,
    { timeout: 120_000 },
  )
  return data
}

export default api

