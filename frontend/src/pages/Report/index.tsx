import { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { NavBar, Toast, Card, Tag, Divider } from 'antd-mobile'
import { getReport, generateReport, type GenerateReportPayload } from '../../services/api'
import { ApiError } from '../../services/api'
import { ACCOUNT_MAP } from '../../constants/accounts'
import { STATUS_MAP } from '../../constants/status'
import type { ReportResponse } from '../../types'
import PatternSwiper from '../../components/PatternCard/PatternSwiper'
import BacktestSwiper from '../../components/Charts/BacktestSwiper'
import PnlChart from '../../components/Charts/PnlChart'
import GeneratingProgress from '../../components/GeneratingProgress'
import './index.css'

/**
 * Strip JSON blocks, code fences, and markdown formatting from LLM output.
 * Defensive filter — backend should already clean, this is the safety net.
 */
function cleanAiText(raw: string): string {
  return raw
    .replace(/```[\w]*\n?/g, '')                        // code fences
    .replace(/#{1,6}\s?/g, '')                           // ## headers
    .replace(/\*{1,2}([^*]+)\*{1,2}/g, '$1')             // **bold** / *italic*
    .replace(/\{[\s\S]*?\}/g, '')                        // {...} JSON blocks
    .replace(/\n{3,}/g, '\n\n')                          // collapse blank lines
    .trim()
}

function SuggestionList({ text }: { text: string }) {
  const cleaned = cleanAiText(text)
  const lines = cleaned
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.length > 0)

  const stripPrefix = (line: string) =>
    line.replace(/^[\d]+[.、\)]\s*/, '').replace(/^[-•①②③④⑤⑥⑦⑧⑨⑩]\s*/, '').trim()

  if (lines.length <= 1) {
    return <p className="ai-text">{cleaned}</p>
  }

  return (
    <ul className="suggestion-list">
      {lines.map((line, i) => (
        <li key={i}>{stripPrefix(line)}</li>
      ))}
    </ul>
  )
}

export default function Report() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string>('')
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const pollCountRef = useRef(0)
  const startedAtRef = useRef<number>(Date.now())
  const MAX_POLL_COUNT = 60

  useEffect(() => {
    // ── Pending mode: id === 'pending', need to call generate first ──
    if (id === 'pending') {
      const params = (location.state as { params?: GenerateReportPayload } | null)?.params
      if (!params) { navigate('/', { replace: true }); return }

      generateReport(params)
        .then((r) => {
          // Replace URL with real report id, then start polling
          navigate(`/report/${r.id}`, { replace: true })
        })
        .catch((err) => {
          const msg = err instanceof ApiError ? err.message : '请求失败，请确认后端服务已启动'
          setErrorMessage(msg)
          setFetchError(true)
          setLoading(false)
          Toast.show({ icon: 'fail', content: msg, duration: 3000 })
        })
      return
    }

    if (!id) return

    const stopPolling = () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }

    const fetchReport = async () => {
      pollCountRef.current += 1

      if (pollCountRef.current > MAX_POLL_COUNT) {
        stopPolling()
        setErrorMessage('报告生成超时，请稍后重试')
        setFetchError(true)
        setLoading(false)
        Toast.show({ icon: 'fail', content: '报告生成超时', duration: 3000 })
        return
      }

      try {
        const data = await getReport(Number(id))
        setReport(data)

        if (data.status === 'completed' || data.status === 'failed') {
          setLoading(false)
          stopPolling()
        }
      } catch (err) {
        const msg =
          err instanceof ApiError
            ? err.message
            : '连接失败，请检查后端服务是否运行'
        setErrorMessage(msg)
        setFetchError(true)
        setLoading(false)
        stopPolling()
        Toast.show({ icon: 'fail', content: msg, duration: 3000 })
      }
    }

    fetchReport()
    pollingRef.current = setInterval(fetchReport, 3000)

    return () => { stopPolling() }
  }, [id, location.state])

  const statusInfo = STATUS_MAP[report?.status ?? 'pending']
  const account = report ? ACCOUNT_MAP[report.user_id] : null

  return (
    <div className="report-page">
      <NavBar onBack={() => navigate(-1)}>
        {account ? `${account.brokerName} ${account.maskedAccount}` : '复盘报告'}
        {report && (
          <Tag color={statusInfo.tagColor} style={{ marginLeft: 8 }}>
            {statusInfo.text}
          </Tag>
        )}
      </NavBar>

      <div className="report-content">
        {(loading || fetchError || report?.status === 'failed') && report?.status !== 'completed' ? (
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
                <p>{cleanAiText(report.ai_style_description)}</p>
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
            {(() => {
              const effectiveScenarios = report.backtest?.scenarios.filter(
                (s) => s.improvement > 0
              ) ?? []
              if (effectiveScenarios.length === 0) return null
              const bestEffective = effectiveScenarios.reduce((a, b) =>
                a.improvement >= b.improvement ? a : b
              ).name
              return (
                <section className="report-section">
                  <h3 className="section-title">回测对比</h3>
                  <BacktestSwiper
                    scenarios={effectiveScenarios}
                    bestScenario={bestEffective}
                  />
                </section>
              )
            })()}

            {/* 8. AI 复盘总结 */}
            {report.ai_summary && (
              <section className="report-section">
                <Card title="AI 复盘总结">
                  <p className="ai-text">{cleanAiText(report.ai_summary)}</p>
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
