import { Swiper, Tag } from 'antd-mobile'
import type { BacktestScenario } from '../../types'
import { formatPnlValue } from '../../constants/accounts'
import BacktestChart from './BacktestChart'
import './BacktestSwiper.css'

interface Props {
  scenarios: BacktestScenario[]
  bestScenario: string
  flat?: boolean
}

export default function BacktestSwiper({ scenarios, bestScenario, flat = false }: Props) {
  if (!scenarios || scenarios.length === 0) return null

  const renderSlide = (scenario: BacktestScenario) => {
    const isBest = scenario.name === bestScenario
    const improved = scenario.improvement > 0

    return (
      <div className="backtest-slide" key={scenario.name}>
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

        {scenario.description && (
          <p className="backtest-slide-rationale">{scenario.description}</p>
        )}

        <div className="backtest-pnl-row">
          <div className="backtest-pnl-block">
            <span className="backtest-pnl-label">原始盈亏</span>
            <span className={`backtest-pnl-val ${scenario.original_pnl >= 0 ? 'bt-positive' : 'bt-negative'}`}>
              {formatPnlValue(scenario.original_pnl)}
            </span>
          </div>

          <div className="backtest-pnl-divider">→</div>

          <div className="backtest-pnl-block">
            <span className="backtest-pnl-label">优化后</span>
            <span className={`backtest-pnl-val ${scenario.adjusted_pnl >= 0 ? 'bt-positive' : 'bt-negative'}`}>
              {formatPnlValue(scenario.adjusted_pnl)}
            </span>
          </div>

          <div className="backtest-pnl-block backtest-pnl-improve">
            <span className="backtest-pnl-label">改善</span>
            <span className={`backtest-improve-val ${improved ? 'bt-positive' : 'bt-negative'}`}>
              {improved ? '▲' : '▼'} {formatPnlValue(scenario.improvement)}
            </span>
            <span className="backtest-improve-pct">
              {scenario.improvement_pct >= 0 ? '+' : ''}{scenario.improvement_pct.toFixed(1)}%
            </span>
          </div>
        </div>

        <div className="backtest-chart-inner">
          <BacktestChart scenario={scenario} />
        </div>

        {scenario.ai_interpretation && (
          <div className="backtest-ai-interpretation">
            💡 {scenario.ai_interpretation}
          </div>
        )}
      </div>
    )
  }

  if (flat) {
    return (
      <div className="backtest-flat-list">
        {scenarios.map(renderSlide)}
      </div>
    )
  }

  return (
    <div className="backtest-swiper-wrapper">
      <Swiper
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
        {scenarios.map((scenario) => (
          <Swiper.Item key={scenario.name}>
            {renderSlide(scenario)}
          </Swiper.Item>
        ))}
      </Swiper>
    </div>
  )
}
