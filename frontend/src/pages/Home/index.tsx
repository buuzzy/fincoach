import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  NavBar,
  Button,
  Picker,
  DatePicker,
  Toast,
  SpinLoading,
  Dialog,
} from 'antd-mobile'
import dayjs from 'dayjs'
import { getUsers, generateReport, ApiError } from '../../services/api'
import { useAuth } from '../../contexts/AuthContext'
import type { UserListItem } from '../../types'
import './index.css'

export default function Home() {
  const navigate = useNavigate()
  const { logout } = useAuth()

  const [users, setUsers] = useState<UserListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)

  const [selectedUserId, setSelectedUserId] = useState<number | null>(null)
  // MVP: mock data covers 2025-01-01 ~ 2025-03-31
  const [periodStart, setPeriodStart] = useState<Date>(
    dayjs('2025-01-01').toDate(),
  )
  const [periodEnd, setPeriodEnd] = useState<Date>(dayjs('2025-03-31').toDate())

  const [showUserPicker, setShowUserPicker] = useState(false)
  const [showStartPicker, setShowStartPicker] = useState(false)
  const [showEndPicker, setShowEndPicker] = useState(false)

  const loadedRef = useRef(false)

  useEffect(() => {
    if (loadedRef.current) return
    loadedRef.current = true
    setLoading(true)
    getUsers()
      .then((list) => setUsers(list))
      .catch((err) => {
        const msg = err instanceof ApiError ? err.message : '获取用户列表失败'
        Toast.show({ content: msg, icon: 'fail' })
      })
      .finally(() => setLoading(false))
  }, [])

  const userColumns = [
    users.map((u) => ({ label: u.name, value: String(u.id) })),
  ]

  const selectedUserName =
    users.find((u) => u.id === selectedUserId)?.name ?? '请选择用户'

  const handleGenerate = async () => {
    if (!selectedUserId) {
      Toast.show({ content: '请先选择用户' })
      return
    }
    setGenerating(true)
    try {
      const report = await generateReport({
        user_id: selectedUserId,
        period_start: dayjs(periodStart).format('YYYY-MM-DD'),
        period_end: dayjs(periodEnd).format('YYYY-MM-DD'),
      })
      // 后端立即返回 report id，分析在后台运行，直接跳转到报告页
      navigate(`/report/${report.id}`)
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : '请求失败，请确认后端服务已启动'
      Toast.show({ content: msg, icon: 'fail' })
      setGenerating(false)
    }
  }

  const handleLogout = () => {
    Dialog.confirm({
      content: '确定要退出登录吗？',
      confirmText: '退出',
      cancelText: '取消',
      onConfirm: () => {
        logout()
        navigate('/login', { replace: true })
      },
    })
  }

  return (
    <div className="home-page">
      <NavBar
        back={null}
        right={
          <span
            style={{ fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer' }}
            onClick={handleLogout}
          >
            退出
          </span>
        }
      >
        交易复盘分析
      </NavBar>

      <div className="home-content">
        {loading ? (
          <div className="loading-wrap">
            <SpinLoading />
          </div>
        ) : (
          <>
            {/* User Selector */}
            <div className="form-item" onClick={() => setShowUserPicker(true)}>
              <span className="form-label">选择用户</span>
              <span className="form-value">{selectedUserName}</span>
            </div>

            <Picker
              columns={userColumns}
              visible={showUserPicker}
              onClose={() => setShowUserPicker(false)}
              onConfirm={(val) => {
                if (val[0]) setSelectedUserId(Number(val[0]))
              }}
            />

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
              生成报告
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
          </>
        )}
      </div>
    </div>
  )
}
