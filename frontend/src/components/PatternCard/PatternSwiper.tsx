import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Swiper, Tag } from 'antd-mobile'
import type { PatternResult, PatternExampleBase } from '../../types'
import KLineCard from '../KLineCarousel/KLineCard'
import './PatternSwiper.css'

interface Props {
  patterns: PatternResult[]
}

const patternColorMap: Record<string, string> = {
  chase_high: '#ff4d4f',
  early_profit: '#faad14',
  slow_stop_loss: '#ff7a45',
  hold_too_long: '#13c2c2',
  fee_drag: '#eb2f96',
}

const patternIconMap: Record<string, string> = {
  chase_high: '📈',
  early_profit: '💰',
  slow_stop_loss: '🐌',
  hold_too_long: '⏰',
  fee_drag: '💸',
}

export default function PatternSwiper({ patterns }: Props) {
  const navigate = useNavigate()
  const [activeIndex, setActiveIndex] = useState(0)

  if (!patterns || patterns.length === 0) return null

  return (
    <div className="pattern-swiper-wrapper">
      <Swiper
        onIndexChange={(idx) => setActiveIndex(idx)}
        indicator={(total, current) => (
          <div className="pattern-swiper-dots">
            {Array.from({ length: total }).map((_, i) => (
              <div
                key={i}
                className={`pattern-swiper-dot ${i === current ? 'active' : ''}`}
              />
            ))}
          </div>
        )}
      >
        {patterns.map((pattern, slideIdx) => {
          const color = patternColorMap[pattern.pattern_type] ?? '#999'
          const icon = patternIconMap[pattern.pattern_type] ?? '🔍'

          // Pick the best example (first after sorting by abs pnl, already done backend-side)
          const example = (pattern.examples as PatternExampleBase[]).find(
            (ex) => ex.buy_date && ex.sell_date,
          )

          const pnlVal = typeof example?.pnl === 'number' ? example.pnl : null

          return (
            <Swiper.Item key={pattern.pattern_type}>
              <div className="pattern-slide">
                {/* Header */}
                <div className="pattern-slide-header">
                  <div className="pattern-slide-title">
                    <span className="pattern-slide-icon">{icon}</span>
                    <span className="pattern-slide-name">{pattern.pattern_name}</span>
                    <Tag
                      style={{
                        '--background-color': color,
                        '--text-color': '#fff',
                        '--border-color': color,
                        marginLeft: 6,
                      }}
                      round
                    >
                      {pattern.occurrences}次
                    </Tag>
                  </div>
                  <div className="pattern-slide-impact">
                    影响{' '}
                    <span className={pattern.total_impact >= 0 ? 'positive' : 'negative'}>
                      {pattern.total_impact >= 0 ? '+' : ''}
                      {pattern.total_impact.toFixed(0)}元
                    </span>
                  </div>
                </div>

                {/* Description */}
                <p className="pattern-slide-desc">{pattern.description}</p>

                {/* K-line chart — only for patterns with date info */}
                {example ? (
                  <>
                    <div className="pattern-slide-trade-label">
                      {example.stock} &nbsp;·&nbsp; {example.buy_date} → {example.sell_date}
                      {pnlVal !== null && (
                        <span className={pnlVal >= 0 ? 'positive' : 'negative'}>
                          &nbsp;{pnlVal >= 0 ? '+' : ''}{pnlVal.toFixed(0)}元
                        </span>
                      )}
                    </div>
                    <KLineCard
                      example={example}
                      aiCommentary={pattern.ai_commentary}
                      active={activeIndex === slideIdx}
                    />
                    {example.buy_trade_id && example.sell_trade_id && (
                      <div
                        className="pattern-review-link"
                        onClick={() => navigate(`/trade-review/${example.buy_trade_id}/${example.sell_trade_id}`)}
                      >
                        查看详细复盘 &gt;
                      </div>
                    )}
                  </>
                ) : (
                  <div className="pattern-no-kline">
                    {pattern.ai_commentary ? (
                      <div className="kline-ai-commentary">💡 {pattern.ai_commentary}</div>
                    ) : (
                      <div className="pattern-no-kline-hint">
                        该模式暂无典型 K 线案例
                      </div>
                    )}
                  </div>
                )}
              </div>
            </Swiper.Item>
          )
        })}
      </Swiper>
    </div>
  )
}
