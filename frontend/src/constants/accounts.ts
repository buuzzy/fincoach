// 账户基础数据 —— 单一数据源，AccountSelect / History / Home 等页面共用

export interface AccountInfo {
  userId: number
  brokerName: string
  maskedAccount: string
  logoColor: string
  logoText: string
  totalPnl: number
  winRate: number
  tradePairs: number
}

// Mock 数据覆盖的时段范围
export const DATA_PERIOD_START = '2026-01-14'
export const DATA_PERIOD_END = '2026-03-14'

// 数据来源：从 Supabase mock 数据实际计算的真实值（2026-01-14 ~ 2026-03-14）
export const ACCOUNTS: AccountInfo[] = [
  {
    userId: 1,
    brokerName: '华泰证券A',
    maskedAccount: '****3821',
    logoColor: '#e8652a',
    logoText: 'A',
    totalPnl: -3534,
    winRate: 42.1,
    tradePairs: 19,
  },
  {
    userId: 2,
    brokerName: '华泰证券B',
    maskedAccount: '****0712',
    logoColor: '#e8652a',
    logoText: 'B',
    totalPnl: 86186,
    winRate: 80.0,
    tradePairs: 10,
  },
  {
    userId: 3,
    brokerName: '华泰证券C',
    maskedAccount: '****5967',
    logoColor: '#e8652a',
    logoText: 'C',
    totalPnl: -61148,
    winRate: 5.9,
    tradePairs: 17,
  },
  {
    userId: 4,
    brokerName: '华泰证券D',
    maskedAccount: '****2483',
    logoColor: '#e8652a',
    logoText: 'D',
    totalPnl: 34941,
    winRate: 70.0,
    tradePairs: 10,
  },
  {
    userId: 5,
    brokerName: '华泰证券E',
    maskedAccount: '****8156',
    logoColor: '#e8652a',
    logoText: 'E',
    totalPnl: 1998,
    winRate: 75.0,
    tradePairs: 4,
  },
]

// userId → AccountInfo 快速查找
export const ACCOUNT_MAP: Record<number, AccountInfo> = Object.fromEntries(
  ACCOUNTS.map((a) => [a.userId, a]),
)

// 格式化盈亏显示（带 ¥ 符号）
export function formatPnl(pnl: number): string {
  const abs = Math.abs(pnl)
  const sign = pnl >= 0 ? '+' : '-'
  if (abs >= 10000) return `${sign}¥${(abs / 10000).toFixed(2)}万`
  return `${sign}¥${abs.toFixed(0)}`
}

// 格式化盈亏数值（不带 ¥ 符号，用于图表）
export function formatPnlValue(v: number): string {
  const abs = Math.abs(v)
  const sign = v >= 0 ? '+' : '-'
  if (abs >= 10000) return `${sign}${(abs / 10000).toFixed(1)}万`
  return `${sign}${abs.toFixed(0)}`
}
