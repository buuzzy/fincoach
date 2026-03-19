import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  NavBar,
  Button,
  DatePicker,
  Popup,
  List,
  Tag,
  SpinLoading,
  ErrorBlock,
} from 'antd-mobile'
import dayjs from 'dayjs'
import { ACCOUNT_MAP, DATA_PERIOD_START, DATA_PERIOD_END, formatPnl } from '../../constants/accounts'
import { getClosedTrades } from '../../services/api'
import type { ClosedTrade } from '../../types'
import './index.css'

export default function Home() {
  const navigate = useNavigate()
  const { userId } = useParams<{ userId: string }>()
  const userIdNum = Number(userId)
  const account = ACCOUNT_MAP[userIdNum]

  const [periodStart, setPeriodStart] = useState<Date>(dayjs(DATA_PERIOD_START).toDate())
  const [periodEnd, setPeriodEnd] = useState<Date>(dayjs(DATA_PERIOD_END).toDate())
  const [showStartPicker, setShowStartPicker] = useState(false)
  const [showEndPicker, setShowEndPicker] = useState(false)

  // Trade list drawer
  const [showTradeList, setShowTradeList] = useState(false)
  const [trades, setTrades] = useState<ClosedTrade[]>([])
  const [tradesLoading, setTradesLoading] = useState(false)
  const [tradesError, setTradesError] = useState<string | null>(null)

  if (!account) {
    navigate('/', { replace: true })
    return null
  }

  const handleGenerate = async () => {
    const params = {
      user_id: userIdNum,
      period_start: dayjs(periodStart).format('YYYY-MM-DD'),
      period_end: dayjs(periodEnd).format('YYYY-MM-DD'),
    }
    navigate('/report/pending', { state: { params } })
  }

  const handleViewTrades = async () => {
    setTradesLoading(true)
    setTradesError(null)
    setShowTradeList(true)
    try {
      const data = await getClosedTrades(
        userIdNum,
        dayjs(periodStart).format('YYYY-MM-DD'),
        dayjs(periodEnd).format('YYYY-MM-DD'),
      )
      setTrades(data)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载失败，请重试'
      setTradesError(msg)
    } finally {
      setTradesLoading(false)
    }
  }

  const handleTradeClick = (trade: ClosedTrade) => {
    setShowTradeList(false)
    navigate(`/trade-review/${trade.buy_trade_id}/${trade.sell_trade_id}`)
  }

  return (
    <div className="home-page">
      <NavBar onBack={() => navigate('/')}>复盘分析</NavBar>

      <div className="home-content">
        {/* 账户信息展示 */}
        <div className="account-info-card">
          <span className="account-info-label">当前账户</span>
          <div className="account-info-right">
            <span className="account-info-broker">{account.brokerName}</span>
            <span className="account-info-masked">{account.maskedAccount}</span>
          </div>
        </div>

        {/* Period Start */}
        <div className="form-item" onClick={() => setShowStartPicker(true)}>
          <span className="form-label">开始日期</span>
          <span className="form-value">
            {dayjs(periodStart).format('YYYY-MM-DD')}
          </span>
        </div>

        <DatePicker
          visible={showStartPicker}
          onClose={() => setShowStartPicker(false)}
          onConfirm={(val) => setPeriodStart(val)}
          max={periodEnd}
        />

        {/* Period End */}
        <div className="form-item" onClick={() => setShowEndPicker(true)}>
          <span className="form-label">结束日期</span>
          <span className="form-value">
            {dayjs(periodEnd).format('YYYY-MM-DD')}
          </span>
        </div>

        <DatePicker
          visible={showEndPicker}
          onClose={() => setShowEndPicker(false)}
          onConfirm={(val) => setPeriodEnd(val)}
          min={periodStart}
          max={new Date()}
        />

        {/* Generate Button */}
        <Button
          block
          color="primary"
          size="large"
          className="generate-btn"
          onClick={handleGenerate}
        >
          开始复盘分析
        </Button>

        {/* Single Trade Review Button */}
        <Button
          block
          fill="outline"
          size="large"
          className="trade-review-btn"
          onClick={handleViewTrades}
        >
          查看单笔交易复盘
        </Button>

        {/* History Link */}
        <Button
          block
          fill="none"
          size="large"
          className="history-btn"
          onClick={() => navigate('/history')}
        >
          查看历史报告
        </Button>
      </div>

      {/* Closed trades drawer */}
      <Popup
        visible={showTradeList}
        onMaskClick={() => setShowTradeList(false)}
        position="bottom"
        bodyStyle={{ height: '70vh', borderRadius: '12px 12px 0 0', overflow: 'hidden' }}
      >
        <div className="trade-list-popup">
          <div className="trade-list-header">
            <span className="trade-list-title">已平仓交易</span>
            <span className="trade-list-period">
              {dayjs(periodStart).format('MM/DD')} ~ {dayjs(periodEnd).format('MM/DD')}
            </span>
          </div>

          {tradesLoading && (
            <div className="trade-list-loading">
              <SpinLoading color="primary" />
              <span>加载中…</span>
            </div>
          )}

          {tradesError && (
            <ErrorBlock status="default" title="加载失败" description={tradesError} />
          )}

          {!tradesLoading && !tradesError && trades.length === 0 && (
            <ErrorBlock status="empty" title="暂无已平仓交易" description="该时间段内没有完成的买卖对" />
          )}

          {!tradesLoading && !tradesError && trades.length > 0 && (
            <div className="trade-list-scroll">
              <List>
                {trades.map((trade) => {
                  const isProfit = trade.pnl >= 0
                  const pnlColor = isProfit ? 'var(--profit-color)' : 'var(--loss-color)'
                  const pnlSign  = isProfit ? '+' : ''
                  return (
                    <List.Item
                      key={`${trade.buy_trade_id}-${trade.sell_trade_id}`}
                      onClick={() => handleTradeClick(trade)}
                      arrow
                      extra={
                        <div className="trade-item-right">
                          <span style={{ color: pnlColor, fontWeight: 600 }}>
                            {formatPnl(trade.pnl)}
                          </span>
                          <span className="trade-item-pct" style={{ color: pnlColor }}>
                            {pnlSign}{trade.pnl_pct.toFixed(2)}%
                          </span>
                        </div>
                      }
                    >
                      <div className="trade-item-main">
                        <span className="trade-item-name">{trade.stock_name}</span>
                        <Tag color="default" fill="outline" className="trade-item-code">
                          {trade.stock_code}
                        </Tag>
                      </div>
                      <div className="trade-item-sub">
                        <span>{dayjs(trade.buy_time).format('MM/DD')} → {dayjs(trade.sell_time).format('MM/DD')}</span>
                        <span>持仓 {trade.hold_days} 天</span>
                        <span>×{trade.quantity.toLocaleString()} 股</span>
                      </div>
                    </List.Item>
                  )
                })}
              </List>
            </div>
          )}
        </div>
      </Popup>
    </div>
  )
}
