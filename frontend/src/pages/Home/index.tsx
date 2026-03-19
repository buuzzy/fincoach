import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  NavBar,
  Button,
  DatePicker,
  Toast,
} from 'antd-mobile'
import dayjs from 'dayjs'
import { generateReport, ApiError } from '../../services/api'
import { ACCOUNT_MAP } from '../../constants/accounts'
import './index.css'

export default function Home() {
  const navigate = useNavigate()
  const { userId } = useParams<{ userId: string }>()
  const userIdNum = Number(userId)
  const account = ACCOUNT_MAP[userIdNum]

  const [generating, setGenerating] = useState(false)
  // MVP: mock data covers 2025-01-01 ~ 2025-03-31
  const [periodStart, setPeriodStart] = useState<Date>(dayjs('2025-01-01').toDate())
  const [periodEnd, setPeriodEnd] = useState<Date>(dayjs('2025-03-31').toDate())
  const [showStartPicker, setShowStartPicker] = useState(false)
  const [showEndPicker, setShowEndPicker] = useState(false)

  if (!account) {
    navigate('/', { replace: true })
    return null
  }

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const report = await generateReport({
        user_id: userIdNum,
        period_start: dayjs(periodStart).format('YYYY-MM-DD'),
        period_end: dayjs(periodEnd).format('YYYY-MM-DD'),
      })
      navigate(`/report/${report.id}`)
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : '请求失败，请确认后端服务已启动'
      Toast.show({ content: msg, icon: 'fail' })
      setGenerating(false)
    }
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
          loading={generating}
          onClick={handleGenerate}
        >
          开始复盘分析
        </Button>

        {/* History Link */}
        <Button
          block
          fill="outline"
          size="large"
          className="history-btn"
          onClick={() => navigate('/history')}
        >
          查看历史报告
        </Button>
      </div>
    </div>
  )
}
