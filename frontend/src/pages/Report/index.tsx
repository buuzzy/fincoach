import { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { NavBar, Toast, Card, Tag, Divider } from 'antd-mobile'
import { getReport } from '../../services/api'
import { ApiError } from '../../services/api'
import { ACCOUNT_MAP } from '../../constants/accounts'
import type { ReportResponse } from '../../types'
import PatternSwiper from '../../components/PatternCard/PatternSwiper'
import BacktestChart from '../../components/Charts/BacktestChart'
import BacktestSwiper from '../../components/Charts/BacktestSwiper'
import PnlChart from '../../components/Charts/PnlChart'
import GeneratingProgress from '../../components/GeneratingProgress'
import './index.css'

/** 把 LLM 返回的建议文本渲染成分条列表。
 *  支持 "1. xxx" / "- xxx" 开头，或纯换行分段。
 */
function SuggestionList({ text }: { text: string }) {
  const lines = text
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.length > 0)

  // 去掉行首的序号前缀 "1." / "1、" / "-" / "•"
  const clean = (line: string) =>
    line.replace(/^[\d]+[.、\)]\s*/, '').replace(/^[-•]\s*/, '').trim()

  if (lines.length <= 1) {
    // 只有一行，直接段落展示
    return <p className="ai-text">{text}</p>
  }

  return (
    <ul className="suggestion-list">
      {lines.map((line, i) => (
        <li key={i}>{clean(line)}</li>
      ))}
    </ul>
  )
}

export default function Report() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [activeScenario, setActiveScenario] = useState<string>('')
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startedAtRef = useRef<number>(Date.now())

  useEffect(() => {
    if (!id) return

    const fetchReport = async () => {
      try {
        const data = await getReport(Number(id))
        setReport(data)

        if (data.status === 'completed' || data.status === 'failed') {
          setLoading(false)
          if (pollingRef.current) {
            clearInterval(pollingRef.current)
            pollingRef.current = null
          }
          // Init active scenario to best
          if (data.backtest?.best_scenario && !activeScenario) {
            setActiveScenario(data.backtest.best_scenario)
          }
        }
      } catch (err) {
        // 网络/服务异常：停止轮询，显示失败状态
        const msg =
          err instanceof ApiError
            ? err.message
            : '连接失败，请检查后端服务是否运行'
        setErrorMessage(msg)
        setFetchError(true)
        setLoading(false)
        if (pollingRef.current) {
          clearInterval(pollingRef.current)
          pollingRef.current = null
        }
        Toast.show({ icon: 'fail', content: msg, duration: 3000 })
      }
    }

    fetchReport()
    pollingRef.current = setInterval(fetchReport, 3000)

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [id])

  const statusMap: Record<string, { text: string; color: string }> = {
    pending: { text: '等待中', color: 'default' },
    generating: { text: '生成中', color: 'warning' },
    completed: { text: '已完成', color: 'success' },
    failed: { text: '失败', color: 'danger' },
  }

  const statusInfo = statusMap[report?.status ?? 'pending']
  const account = report ? ACCOUNT_MAP[report.user_id] : null

  return (
    <div className="report-page">
      <NavBar onBack={() => navigate(-1)}>
        {account ? `${account.brokerName} ${account.maskedAccount}` : '复盘报告'}
        {report && (
          <Tag color={statusInfo.color} style={{ marginLeft: 8 }}>
            {statusInfo.text}
          </Tag>
        )}
      </NavBar>

      <div className="report-content">
        {(loading || fetchError || report?.status === 'failed') && !report?.status.match(/completed/) ? (
          <GeneratingProgress
            startedAt={startedAtRef.current}
            failed={fetchError || report?.status === 'failed'}
            failedReason={
              fetchError
                ? errorMessage
                : report?.status === 'failed'
                  ? (report.error_message ? '分析流程异常，请重试' : '报告生成失败')
                  : undefined
            }
            onRetry={() => navigate('/')}
          />
        ) : report && report.status === 'completed' ? (
          <>
            {/* 1. 数据预警横幅 */}
            {report.diagnosis?.data_warning && (
              <div className={`warning-banner ${report.diagnosis.data_warning}`}>
                ⚠️{' '}
                {report.diagnosis.data_warning === 'insufficient'
                  ? `当前仅 ${report.profile?.trade_count} 笔交易，样本不足，分析结论仅供参考`
                  : `当前 ${report.profile?.trade_count} 笔交易，建议积累更多数据后参考结论`}
              </div>
            )}

            {/* 2. 交易风格 */}
            {report.ai_style_description && (
              <div className="style-description-card">
                <div className="card-title">📊 本期交易风格</div>
                <p>{report.ai_style_description}</p>
              </div>
            )}

            {/* 3. 交易概览（含用户名，去掉 UserProfileCard） */}
            {report.profile && (
              <section className="report-section">
                <Card title="交易概览">
                  <div className="stats-grid">
                    <div className="stat-item">
                      <span className="stat-value">{report.profile.trade_count}</span>
                      <span className="stat-label">总交易次数</span>
                    </div>
                    <div className="stat-item">
                      <span className={`stat-value ${report.profile.total_pnl >= 0 ? 'positive' : 'negative'}`}>
                        {report.profile.total_pnl >= 0 ? '+' : ''}
                        {report.profile.total_pnl.toFixed(2)}
                      </span>
                      <span className="stat-label">总盈亏</span>
                    </div>
                    <div className="stat-item">
                      <span className="stat-value">
                        {(report.profile.win_rate * 100).toFixed(1)}%
                      </span>
                      <span className="stat-label">胜率</span>
                    </div>
                    <div className="stat-item">
                      <span className="stat-value">
                        {report.profile.avg_holding_days.toFixed(1)}天
                      </span>
                      <span className="stat-label">平均持仓</span>
                    </div>
                  </div>
                </Card>
              </section>
            )}

            {/* 4. 盈亏分布 */}
            {report.profile && (
              <section className="report-section">
                <Card title="盈亏分布">
                  <PnlChart profile={report.profile} />
                </Card>
              </section>
            )}

            {/* 5. 交易模式横滑卡片 */}
            {report.patterns && report.patterns.length > 0 && (
              <section className="report-section">
                <h3 className="section-title">检测到的交易模式</h3>
                <PatternSwiper patterns={report.patterns} />
              </section>
            )}

            {/* 6. 诊断结果 */}
            {report.diagnosis && (
              <section className="report-section">
                <Card title="诊断结果">
                  <div className="severity-bar">
                    <span>严重程度</span>
                    <div className="severity-track">
                      <div
                        className="severity-fill"
                        style={{
                          width: `${report.diagnosis.severity_score}%`,
                          backgroundColor:
                            report.diagnosis.severity_score > 70
                              ? 'var(--danger-color)'
                              : report.diagnosis.severity_score > 40
                                ? 'var(--warning-color)'
                                : 'var(--success-color)',
                        }}
                      />
                    </div>
                    <span>{report.diagnosis.severity_score.toFixed(0)}分</span>
                  </div>
                  <Divider />
                  <div className="diagnosis-issues">
                    <h4>主要问题</h4>
                    <ul>
                      {report.diagnosis.primary_issues.map((issue, i) => (
                        <li key={i}>{issue}</li>
                      ))}
                    </ul>
                  </div>
                  <Divider />
                  <p className="diagnosis-summary">{report.diagnosis.summary}</p>
                </Card>
              </section>
            )}

            {/* 7. 回测对比 */}
            {report.backtest && report.backtest.scenarios.length > 0 && (
              <section className="report-section">
                <h3 className="section-title">回测对比</h3>
                {/* Scenario swiper cards */}
                <BacktestSwiper
                  scenarios={report.backtest.scenarios}
                  bestScenario={report.backtest.best_scenario}
                  onActiveChange={(name) => setActiveScenario(name)}
                />
                {/* Multi-scenario cumulative PnL chart */}
                <div className="backtest-chart-wrap">
                  <BacktestChart
                    scenarios={report.backtest.scenarios}
                    bestScenario={report.backtest.best_scenario}
                    activeScenario={activeScenario || report.backtest.best_scenario}
                  />
                </div>
              </section>
            )}

            {/* 8. AI 复盘总结 */}
            {report.ai_summary && (
              <section className="report-section">
                <Card title="AI 复盘总结">
                  <p className="ai-text">{report.ai_summary}</p>
                </Card>
              </section>
            )}

            {/* 9. 改进建议 */}
            {report.ai_suggestions && (
              <section className="report-section">
                <Card title="改进建议">
                  <SuggestionList text={report.ai_suggestions} />
                </Card>
              </section>
            )}
          </>
        ) : (
          <div className="error-section">
            <p>报告生成失败或不存在</p>
          </div>
        )}
      </div>
    </div>
  )
}
