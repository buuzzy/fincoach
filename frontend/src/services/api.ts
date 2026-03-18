import axios, { AxiosError } from 'axios'
import type {
  UserListItem,
  UserProfile,
  ReportResponse,
  ReportListItem,
  MarketDataResponse,
} from '../types'

const TOKEN_KEY = 'tm_access_token'

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
  if (status === 401) return new ApiError('登录已过期，请重新登录', 'unauthorized', status, detail)
  if (status === 404) return new ApiError(detail ?? '资源不存在', 'not_found', status, detail)
  if (status >= 500) return new ApiError(detail ?? '服务器内部错误，请稍后重试', 'server', status, detail)
  if (status >= 400) return new ApiError(detail ?? '请求参数有误', 'client', status, detail)

  return new ApiError('请求失败，请重试', 'client', status, detail)
}

// ── Axios 实例 ───────────────────────────────────────────────────────────────

// 生产环境：VITE_API_BASE_URL=https://fincoach-backend.onrender.com
// 开发环境：空字符串，走 vite proxy → localhost:8000
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '') + '/api'

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 60000,
})

// 请求拦截：自动携带 token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const apiErr = toApiError(error)
    // 401 自动跳回登录页
    if (apiErr.code === 'unauthorized') {
      localStorage.removeItem(TOKEN_KEY)
      window.location.href = '/login'
    }
    return Promise.reject(apiErr)
  },
)

// ─── Auth ───────────────────────────────────────────────────────────

export interface LoginPayload {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const { data } = await api.post<TokenResponse>('/auth/login', payload)
  return data
}

// ─── Users ─────────────────────────────────────────────────────────

export async function getUsers(): Promise<UserListItem[]> {
  const { data } = await api.get<UserListItem[]>('/users/')
  return data
}

export async function getUserProfile(userId: number): Promise<UserProfile> {
  const { data } = await api.get<UserProfile>(`/users/${userId}/profile`)
  return data
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

export default api
