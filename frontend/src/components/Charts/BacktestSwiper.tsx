import { useState } from 'react'
import { Swiper, Tag } from 'antd-mobile'
import type { BacktestScenario } from '../../types'
import './BacktestSwiper.css'

interface Props {
  scenarios: BacktestScenario[]
  bestScenario: string
  onActiveChange?: (scenarioName: string) => void
}

export default function BacktestSwiper({ scenarios, bestScenario, onActiveChange }: Props) {
  const [activeIndex, setActiveIndex] = useState(0)

  if (!scenarios || scenarios.length === 0) return null

  const handleIndexChange = (idx: number) => {
    setActiveIndex(idx)
    onActiveChange?.(scenarios[idx]?.name ?? '')
  }

  return (
    <div className="backtest-swiper-wrapper">
      <Swiper
        onIndexChange={handleIndexChange}
        indicator={(total, current) => (
          <div className="backtest-swiper-dots">
            {Array.from({ length: total }).map((_, i) => (
              <div
                key={i}
                className={`backtest-swiper-dot ${i === current ? 'active' : ''}`}
              />
            ))}
          </div>
        )}
      >
        {scenarios.map((scenario) => {
          const isBest = scenario.name === bestScenario
          const improved = scenario.improvement > 0
          const improvePct = scenario.improvement_pct

          return (
            <Swiper.Item key={scenario.name}>
              <div className="backtest-slide">

                {/* Header */}
                <div className="backtest-slide-header">
                  <div className="backtest-slide-title">
                    <span className="backtest-slide-name">{scenario.name}</span>
                    {isBest && (
                      <Tag
                        style={{
                          '--background-color': '#52c41a',
                          '--text-color': '#fff',
                          '--border-color': '#52c41a',
                          marginLeft: 6,
                        }}
                        round
                      >
                        最佳
                      </Tag>
                    )}
                  </div>
                  <span className="backtest-slide-param">{scenario.param_change}</span>
                </div>

                {/* LLM design rationale */}
                {scenario.description && (
                  <p className="backtest-slide-rationale">{scenario.description}</p>
                )}

                {/* PnL comparison */}
                <div className="backtest-pnl-row">
                  <div className="backtest-pnl-item">
                    <span className="backtest-pnl-label">原始盈亏</span>
                    <span className={`backtest-pnl-val ${scenario.original_pnl >= 0 ? 'positive' : 'negative'}`}>
                      {scenario.original_pnl >= 0 ? '+' : ''}
                      {scenario.original_pnl.toFixed(0)}
                    </span>
                  </div>
                  <div className="backtest-pnl-arrow">→</div>
                  <div className="backtest-pnl-item">
                    <span className="backtest-pnl-label">优化后</span>
                    <span className={`backtest-pnl-val ${scenario.adjusted_pnl >= 0 ? 'positive' : 'negative'}`}>
                      {scenario.adjusted_pnl >= 0 ? '+' : ''}
                      {scenario.adjusted_pnl.toFixed(0)}
                    </span>
                  </div>
                  <div className="backtest-pnl-improvement">
                    <span className={`backtest-improvement-val ${improved ? 'positive' : 'negative'}`}>
                      {improved ? '▲' : '▼'} {improved ? '+' : ''}{scenario.improvement.toFixed(0)} 元
                    </span>
                    <span className="backtest-improvement-pct">
                      ({improvePct >= 0 ? '+' : ''}{improvePct.toFixed(1)}%)
                    </span>
                  </div>
                </div>

                {/* AI interpretation */}
                {scenario.ai_interpretation && (
                  <div className="backtest-ai-interpretation">
                    💡 {scenario.ai_interpretation}
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
