import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { NavBar, SpinLoading, Toast } from 'antd-mobile'
import dayjs from 'dayjs'
import { getReports } from '../../services/api'
import { ACCOUNT_MAP } from '../../constants/accounts'
import type { ReportListItem } from '../../types'
import './index.css'

const statusMap: Record<string, { text: string; color: string }> = {
  pending:    { text: '等待中', color: '#aaa'     },
  generating: { text: '生成中', color: '#fa8c16'  },
  completed:  { text: '已完成', color: '#52c41a'  },
  failed:     { text: '失败',   color: '#ff4d4f'  },
}

export default function History() {
  const navigate = useNavigate()
  const [reports, setReports] = useState<ReportListItem[]>([])
  const [loading, setLoading] = useState(true)
  const loadedRef = useRef(false)

  useEffect(() => {
    if (loadedRef.current) return
    loadedRef.current = true
    getReports()
      .then((list) => setReports(list))
      .catch(() => Toast.show({ content: '获取报告列表失败', icon: 'fail' }))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="history-page">
      <NavBar onBack={() => navigate(-1)}>历史报告</NavBar>

      <div className="history-content">
        {loading ? (
          <div className="loading-wrap"><SpinLoading /></div>
        ) : reports.length === 0 ? (
          <div className="empty-wrap">暂无报告记录</div>
        ) : (
          <div className="report-list">
            {reports.map((r) => {
              const status = statusMap[r.status] ?? statusMap.pending
              const hasPnl = r.total_pnl != null
              const pnlPositive = (r.total_pnl ?? 0) >= 0
              const account = ACCOUNT_MAP[r.user_id]

              return (
                <div
                  key={r.id}
                  className="report-card"
                  onClick={() => navigate(`/report/${r.id}`)}
                >
                  {/* Top row: broker info + status */}
                  <div className="rc-top">
                    <div className="rc-account">
                      {account ? (
                        <>
                          <span className="rc-broker">{account.brokerName}</span>
                          <span className="rc-masked">{account.maskedAccount}</span>
                        </>
                      ) : (
                        <span className="rc-broker">未知账户</span>
                      )}
                    </div>
                    <span className="rc-status" style={{ color: status.color }}>
                      {status.text}
                    </span>
                  </div>

                  {/* Period */}
                  <div className="rc-period">
                    {dayjs(r.period_start).format('YYYY/MM/DD')} – {dayjs(r.period_end).format('YYYY/MM/DD')}
                  </div>

                  {/* Key metrics — only shown when completed */}
                  {r.status === 'completed' && hasPnl && (
                    <div className="rc-metrics">
                      <div className="rc-metric">
                        <span className={`rc-metric-val ${pnlPositive ? 'positive' : 'negative'}`}>
                          {pnlPositive ? '+' : ''}{r.total_pnl!.toFixed(0)}
                        </span>
                        <span className="rc-metric-label">总盈亏(元)</span>
                      </div>
                      {r.win_rate != null && (
                        <div className="rc-metric">
                          <span className="rc-metric-val">
                            {(r.win_rate * 100).toFixed(1)}%
                          </span>
                          <span className="rc-metric-label">胜率</span>
                        </div>
                      )}
                      {r.trade_count != null && (
                        <div className="rc-metric">
                          <span className="rc-metric-val">{r.trade_count}</span>
                          <span className="rc-metric-label">交易笔数</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Bottom: created time */}
                  <div className="rc-time">
                    {dayjs(r.created_at).format('MM-DD HH:mm')} 生成
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
