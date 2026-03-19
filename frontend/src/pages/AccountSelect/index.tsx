import { useNavigate } from 'react-router-dom'
import { NavBar, Button } from 'antd-mobile'
import { RightOutline } from 'antd-mobile-icons'
import { useAuth } from '../../contexts/AuthContext'
import './index.css'

interface AccountInfo {
  userId: number
  brokerName: string
  maskedAccount: string
  logoColor: string
  logoText: string
  totalPnl: number
  winRate: number
  tradePairs: number
}

// 数据来源：从 Supabase mock 数据实际计算的真实值
const ACCOUNTS: AccountInfo[] = [
  {
    userId: 1,
    brokerName: '华泰证券',
    maskedAccount: '****3821',
    logoColor: '#e8652a',
    logoText: '华泰',
    totalPnl: -66283,
    winRate: 35.9,
    tradePairs: 39,
  },
  {
    userId: 2,
    brokerName: '招商证券',
    maskedAccount: '****0712',
    logoColor: '#c1272d',
    logoText: '招商',
    totalPnl: 147807,
    winRate: 75.0,
    tradePairs: 16,
  },
  {
    userId: 3,
    brokerName: '东方财富证券',
    maskedAccount: '****5967',
    logoColor: '#e05b16',
    logoText: '东财',
    totalPnl: 16896,
    winRate: 55.6,
    tradePairs: 27,
  },
  {
    userId: 4,
    brokerName: '中信证券',
    maskedAccount: '****2483',
    logoColor: '#1a3fa3',
    logoText: '中信',
    totalPnl: 86209,
    winRate: 54.2,
    tradePairs: 24,
  },
  {
    userId: 5,
    brokerName: '国泰海通证券',
    maskedAccount: '****8156',
    logoColor: '#0e7a4c',
    logoText: '海通',
    totalPnl: -883,
    winRate: 50.0,
    tradePairs: 4,
  },
]

function formatPnl(pnl: number): string {
  const abs = Math.abs(pnl)
  if (abs >= 10000) {
    return `${pnl >= 0 ? '+' : '-'}¥${(abs / 10000).toFixed(2)}万`
  }
  return `${pnl >= 0 ? '+' : '-'}¥${abs.toFixed(0)}`
}

export default function AccountSelect() {
  const navigate = useNavigate()
  const { logout } = useAuth()

  const handleSelect = (userId: number) => {
    navigate(`/home/${userId}`)
  }

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="account-select-page">
      <NavBar
        back={null}
        right={
          <span
            style={{ fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer' }}
            onClick={handleLogout}
          >
            退出
          </span>
        }
      >
        我的账户
      </NavBar>

      <div className="account-select-header">
        <p className="account-select-greeting">选择复盘账户</p>
        <p className="account-select-subtitle">选择一个交易账户开始 AI 复盘分析</p>
      </div>

      <div className="account-list">
        {ACCOUNTS.map((account) => {
          const pnlPositive = account.totalPnl >= 0
          return (
            <div
              key={account.userId}
              className="account-card"
              onClick={() => handleSelect(account.userId)}
            >
              {/* Broker logo */}
              <div
                className="broker-logo"
                style={{ background: account.logoColor }}
              >
                {account.logoText}
              </div>

              {/* Card body */}
              <div className="account-card-body">
                <div className="account-broker-name">{account.brokerName}</div>
                <div className="account-masked">交易账户：{account.maskedAccount}</div>
                <div className="account-metrics">
                  <div className="account-metric">
                    <span className={`account-metric-val ${pnlPositive ? 'positive' : 'negative'}`}>
                      {formatPnl(account.totalPnl)}
                    </span>
                    <span className="account-metric-label">本期盈亏</span>
                  </div>
                  <div className="account-metric">
                    <span className="account-metric-val neutral">
                      {account.winRate}%
                    </span>
                    <span className="account-metric-label">胜率</span>
                  </div>
                  <div className="account-metric">
                    <span className="account-metric-val neutral">
                      {account.tradePairs}笔
                    </span>
                    <span className="account-metric-label">交易笔数</span>
                  </div>
                </div>
              </div>

              <RightOutline className="account-card-arrow" />
            </div>
          )
        })}
      </div>

      {/* 历史报告入口 */}
      <div className="history-entry">
        <Button
          block
          fill="outline"
          size="large"
          onClick={() => navigate('/history')}
        >
          查看历史报告
        </Button>
      </div>
    </div>
  )
}
