import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { NavBar, Tag, SpinLoading, ErrorBlock } from 'antd-mobile'
import dayjs from 'dayjs'
import { getTradeReview } from '../../services/api'
import type { TradeReviewResponse } from '../../types'
import './index.css'

export default function TradeReview() {
  const navigate = useNavigate()
  const { buyTradeId, sellTradeId } = useParams<{
    buyTradeId: string
    sellTradeId: string
  }>()

  const [review, setReview] = useState<TradeReviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!buyTradeId || !sellTradeId) return
    setLoading(true)
    getTradeReview(Number(buyTradeId), Number(sellTradeId))
      .then(setReview)
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : '加载失败，请重试')
      })
      .finally(() => setLoading(false))
  }, [buyTradeId, sellTradeId])

  const isProfit   = (review?.pnl ?? 0) >= 0
  const pnlColor   = isProfit ? 'var(--profit-color)' : 'var(--loss-color)'
  const pnlSign    = isProfit ? '+' : ''

  return (
    <div className="trade-review-page">
      <NavBar onBack={() => navigate(-1)}>单笔交易复盘</NavBar>

      {loading && (
        <div className="tr-loading">
          <SpinLoading color="primary" />
          <span>正在生成复盘报告…</span>
        </div>
      )}

      {error && !loading && (
        <ErrorBlock status="default" title="加载失败" description={error} />
      )}

      {!loading && !error && review && (
        <div className="tr-content">
          {/* ── 基本信息卡 ── */}
          <div className="tr-card tr-header-card">
            <div className="tr-stock-row">
              <span className="tr-stock-name">{review.stock_name}</span>
              <Tag color="default" fill="outline">{review.stock_code}</Tag>
            </div>
            <div className="tr-pnl-row">
              <span className="tr-pnl-amount" style={{ color: pnlColor }}>
                {pnlSign}{review.pnl >= 0
                  ? `+¥${Math.abs(review.pnl).toFixed(2)}`
                  : `-¥${Math.abs(review.pnl).toFixed(2)}`}
              </span>
              <span className="tr-pnl-pct" style={{ color: pnlColor }}>
                {pnlSign}{review.pnl_pct.toFixed(2)}%
              </span>
            </div>
            <div className="tr-meta-grid">
              <div className="tr-meta-item">
                <span className="tr-meta-label">买入</span>
                <span className="tr-meta-value">¥{review.buy_price.toFixed(2)}</span>
                <span className="tr-meta-sub">{dayjs(review.buy_time).format('MM/DD HH:mm')}</span>
              </div>
              <div className="tr-meta-item">
                <span className="tr-meta-label">卖出</span>
                <span className="tr-meta-value">¥{review.sell_price.toFixed(2)}</span>
                <span className="tr-meta-sub">{dayjs(review.sell_time).format('MM/DD HH:mm')}</span>
              </div>
              <div className="tr-meta-item">
                <span className="tr-meta-label">持仓</span>
                <span className="tr-meta-value">{review.hold_days} 天</span>
              </div>
              <div className="tr-meta-item">
                <span className="tr-meta-label">数量</span>
                <span className="tr-meta-value">{review.quantity.toLocaleString()} 股</span>
              </div>
            </div>
          </div>

          {/* ── K线走势 ── */}
          {review.kline.length > 0 && (
            <div className="tr-card">
              <h3 className="tr-section-title">持仓期间走势</h3>
              <div className="tr-kline-table">
                <div className="tr-kline-head">
                  <span>日期</span>
                  <span>收盘</span>
                  <span>涨跌幅</span>
                </div>
                {review.kline.map((bar) => {
                  const chgColor = bar.change_pct >= 0 ? 'var(--profit-color)' : 'var(--loss-color)'
                  const chgSign  = bar.change_pct >= 0 ? '+' : ''
                  return (
                    <div className="tr-kline-row" key={bar.date}>
                      <span className="tr-kline-date">{bar.date.slice(5)}</span>
                      <span className="tr-kline-close">¥{bar.close.toFixed(2)}</span>
                      <span className="tr-kline-chg" style={{ color: chgColor }}>
                        {chgSign}{bar.change_pct.toFixed(2)}%
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ── 相关资讯 ── */}
          <div className="tr-card">
            <h3 className="tr-section-title">持仓期间相关资讯</h3>
            {review.news.length === 0 ? (
              <p className="tr-empty-text">持仓期间暂无相关资讯记录</p>
            ) : (
              <div className="tr-news-list">
                {review.news.map((item, idx) => (
                  <div className="tr-news-item" key={idx}>
                    <div className="tr-news-meta">
                      <span className="tr-news-date">{item.publish_time}</span>
                      <Tag color="primary" fill="outline" className="tr-news-source">
                        {item.source}
                      </Tag>
                    </div>
                    <p className="tr-news-title">{item.title}</p>
                    {item.summary && (
                      <p className="tr-news-summary">{item.summary.slice(0, 120)}…</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── AI 情景还原 ── */}
          <div className="tr-card">
            <h3 className="tr-section-title">情景还原</h3>
            {review.status === 'failed' || !review.ai_review ? (
              <p className="tr-empty-text">AI 分析暂时不可用</p>
            ) : (
              <p className="tr-ai-review">{review.ai_review}</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
