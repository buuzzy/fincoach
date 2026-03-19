import { useEffect, useState, useMemo } from 'react'
import { Button } from 'antd-mobile'
import './GeneratingProgress.css'

export interface SubStep {
  text: string
  delayMs: number
}

export interface ProgressStep {
  label: string
  detail: string
  subSteps?: SubStep[]
  durationMs: number
}

const DEFAULT_STEPS: ProgressStep[] = [
  {
    label: '读取交易记录',
    detail: '加载期间内买卖流水…',
    subSteps: [
      { text: '连接数据库，筛选分析期间交易流水', delayMs: 0 },
      { text: '自动配对买入与卖出交易记录', delayMs: 800 },
      { text: '计算每笔交易盈亏及持仓天数', delayMs: 1600 },
    ],
    durationMs: 3000,
  },
  {
    label: '识别交易模式',
    detail: '分析行为模式…',
    subSteps: [
      { text: '扫描追高买入模式（买入价 vs 5日均价）', delayMs: 0 },
      { text: '扫描止盈过早模式（卖出后涨幅分析）', delayMs: 600 },
      { text: '扫描止损过慢模式（亏损幅度检测）', delayMs: 1200 },
      { text: '扫描持仓过久 & 手续费侵蚀模式', delayMs: 1800 },
      { text: '模式扫描完成，汇总检测结果', delayMs: 2500 },
    ],
    durationMs: 6000,
  },
  {
    label: '诊断问题',
    detail: '评估严重程度…',
    subSteps: [
      { text: '评估各模式出现频率与影响金额', delayMs: 0 },
      { text: '计算交易行为健康度评分（0~100）', delayMs: 1000 },
      { text: '识别主要问题与改进方向', delayMs: 2000 },
    ],
    durationMs: 9000,
  },
  {
    label: '回测模拟',
    detail: '推算策略优化空间…',
    subSteps: [
      { text: 'AI 分析账户特征，设计个性化策略方案', delayMs: 0 },
      { text: '模拟方案 1：调整止损参数，回测盈亏变化', delayMs: 800 },
      { text: '模拟方案 2：优化持仓策略，回测盈亏变化', delayMs: 1600 },
      { text: '模拟方案 3：改进入场时机，回测盈亏变化', delayMs: 2400 },
      { text: '回测完成，对比原始与优化结果', delayMs: 3200 },
    ],
    durationMs: 13000,
  },
  {
    label: 'AI 分析生成',
    detail: '生成复盘报告…',
    subSteps: [
      { text: '调用行情工具，获取持仓期间 K 线数据', delayMs: 0 },
      { text: '检索相关市场资讯与新闻', delayMs: 3000 },
      { text: 'AI 综合分析，生成交易行为诊断', delayMs: 8000 },
      { text: '撰写个性化复盘总结与改进建议', delayMs: 18000 },
      { text: '整合模式点评与回测解读', delayMs: 28000 },
    ],
    durationMs: 50000,
  },
]

interface Props {
  startedAt: number
  failed?: boolean
  failedReason?: string
  onRetry?: () => void
  steps?: ProgressStep[]
  title?: string
  hint?: string
  failedTitle?: string
}

export default function GeneratingProgress({
  startedAt,
  failed,
  failedReason,
  onRetry,
  steps = DEFAULT_STEPS,
  title = '正在生成复盘报告',
  hint = '通常需要 30～60 秒，请稍候…',
  failedTitle = '报告生成失败',
}: Props) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (failed) return
    const timer = setInterval(() => {
      setElapsed(Date.now() - startedAt)
    }, 300)
    return () => clearInterval(timer)
  }, [startedAt, failed])

  const currentStepIdx = steps.reduce((acc, step, i) => {
    return elapsed >= step.durationMs ? i : acc
  }, 0)

  const currentStep = steps[currentStepIdx]
  const prevDuration = currentStepIdx === 0 ? 0 : steps[currentStepIdx - 1].durationMs
  const stepDuration = currentStep.durationMs - prevDuration
  const stepElapsed = elapsed - prevDuration
  const stepProgress = Math.min(stepElapsed / stepDuration, 0.95)

  const visibleSubSteps = useMemo(() => {
    const subs = currentStep.subSteps
    if (!subs) return []
    return subs.filter((s) => stepElapsed >= s.delayMs)
  }, [currentStep, stepElapsed])

  if (failed) {
    return (
      <div className="gen-progress">
        <div className="gen-failed-icon">✕</div>
        <div className="gen-failed-title">{failedTitle}</div>
        <p className="gen-failed-hint">
          {failedReason ?? '可能是后端服务异常或 AI 接口超时，请稍后重试'}
        </p>
        {onRetry && (
          <Button color="primary" onClick={onRetry} style={{ marginTop: 16, width: 160 }}>
            重新生成
          </Button>
        )}
      </div>
    )
  }

  return (
    <div className="gen-progress">
      <div className="gen-progress-title">{title}</div>

      <div className="gen-steps">
        {steps.map((step, i) => {
          const done = i < currentStepIdx
          const active = i === currentStepIdx
          return (
            <div key={i} className={`gen-step ${done ? 'done' : active ? 'active' : 'pending'}`}>
              <div className="gen-step-left">
                <div className="gen-step-icon">
                  {done ? '✓' : active ? <span className="gen-dot-spin" /> : <span className="gen-dot-idle" />}
                </div>
                {i < steps.length - 1 && <div className="gen-step-line" />}
              </div>
              <div className="gen-step-right">
                <div className="gen-step-label">{step.label}</div>
                {active && (
                  <>
                    <div className="gen-sub-steps">
                      {visibleSubSteps.map((sub, j) => {
                        const isLatest = j === visibleSubSteps.length - 1
                        return (
                          <div key={j} className={`gen-sub-step ${isLatest ? 'latest' : 'completed'}`}>
                            <span className={`gen-sub-dot ${isLatest ? 'running' : 'done'}`} />
                            <span className="gen-sub-text">{sub.text}</span>
                            {isLatest && <span className="gen-sub-cursor" />}
                          </div>
                        )
                      })}
                    </div>
                    <div className="gen-bar-track">
                      <div className="gen-bar-fill" style={{ width: `${stepProgress * 100}%` }} />
                    </div>
                  </>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <p className="gen-hint">{hint}</p>
    </div>
  )
}
