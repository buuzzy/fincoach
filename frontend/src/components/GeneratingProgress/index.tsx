import { useEffect, useState } from 'react'
import { Button } from 'antd-mobile'
import './GeneratingProgress.css'

export interface ProgressStep {
  label: string
  detail: string
  durationMs: number
}

const DEFAULT_STEPS: ProgressStep[] = [
  { label: '读取交易记录',  detail: '加载期间内买卖流水…',       durationMs: 3000  },
  { label: '识别交易模式',  detail: '分析追高、止损等行为模式…', durationMs: 6000  },
  { label: '诊断问题',      detail: '评估严重程度与主要问题…',   durationMs: 9000  },
  { label: '回测模拟',      detail: '推算策略优化空间…',         durationMs: 13000 },
  { label: 'AI 分析生成',   detail: '调用大模型生成复盘建议…',   durationMs: 50000 },
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
                    <div className="gen-step-detail">{step.detail}</div>
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
