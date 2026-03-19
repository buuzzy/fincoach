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

// 数据来源：从 Supabase mock 数据实际计算的真实值（2026-01-14 ~ 2026-03-14）
export const ACCOUNTS: AccountInfo[] = [
  {
    userId: 1,
    brokerName: '华泰证券',
    maskedAccount: '****3821',
    logoColor: '#e8652a',
    logoText: '华泰',
    totalPnl: -18470,
    winRate: 15.8,
    tradePairs: 19,
  },
  {
    userId: 2,
    brokerName: '招商证券',
    maskedAccount: '****0712',
    logoColor: '#c1272d',
    logoText: '招商',
    totalPnl: -6856,
    winRate: 40.0,
    tradePairs: 10,
  },
  {
    userId: 3,
    brokerName: '东方财富证券',
    maskedAccount: '****5967',
    logoColor: '#e05b16',
    logoText: '东财',
    totalPnl: -57778,
    winRate: 11.8,
    tradePairs: 17,
  },
  {
    userId: 4,
    brokerName: '中信证券',
    maskedAccount: '****2483',
    logoColor: '#1a3fa3',
    logoText: '中信',
    totalPnl: -4342,
    winRate: 50.0,
    tradePairs: 10,
  },
  {
    userId: 5,
    brokerName: '国泰海通证券',
    maskedAccount: '****8156',
    logoColor: '#0e7a4c',
    logoText: '海通',
    totalPnl: -3201,
    winRate: 25.0,
    tradePairs: 4,
  },
]

// userId → AccountInfo 快速查找
export const ACCOUNT_MAP: Record<number, AccountInfo> = Object.fromEntries(
  ACCOUNTS.map((a) => [a.userId, a]),
)

// 格式化盈亏显示
export function formatPnl(pnl: number): string {
  const abs = Math.abs(pnl)
  const sign = pnl >= 0 ? '+' : '-'
  if (abs >= 10000) return `${sign}¥${(abs / 10000).toFixed(2)}万`
  return `${sign}¥${abs.toFixed(0)}`
}
