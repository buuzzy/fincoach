import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Checkbox, Toast, Popup } from 'antd-mobile'
import { useAuth } from '../../contexts/AuthContext'
import { login, ApiError } from '../../services/api'
import './index.css'

export default function Login() {
  const navigate = useNavigate()
  const { setLoggedIn } = useAuth()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [agreed, setAgreed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [showAgreement, setShowAgreement] = useState(false)

  const handleLogin = async () => {
    if (!username.trim() || !password.trim()) {
      Toast.show({ content: '请输入账号和密码', icon: 'fail' })
      return
    }
    if (!agreed) {
      Toast.show({ content: '请先阅读并同意用户协议', icon: 'fail' })
      return
    }
    setLoading(true)
    try {
      await login({ username, password })
      setLoggedIn()
      navigate('/', { replace: true })
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : '登录失败，请重试'
      Toast.show({ content: msg, icon: 'fail' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-hero">
        <div className="login-logo">📈</div>
        <h1 className="login-title">TradeMind AI</h1>
        <p className="login-subtitle">AI 交易时空复盘与行为教练</p>
      </div>

      <div className="login-form">
        {/* 账号输入 */}
        <div className="login-input-wrap">
          <span className="login-input-icon">👤</span>
          <input
            type="text"
            placeholder="请输入账号"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
          />
        </div>

        {/* 密码输入 */}
        <div className="login-input-wrap">
          <span className="login-input-icon">🔒</span>
          <input
            type="password"
            placeholder="请输入密码"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
          />
        </div>

        {/* 授权协议 */}
        <div className="login-agreement" onClick={() => setAgreed((v) => !v)}>
          <Checkbox checked={agreed} onChange={setAgreed} />
          <span className="login-agreement-text">
            我已阅读并同意{' '}
            <a
              className="login-agreement-link"
              onClick={(e) => {
                e.stopPropagation()
                setShowAgreement(true)
              }}
            >
              《用户协议与数据授权声明》
            </a>
          </span>
        </div>

        {/* 登录按钮 */}
        <Button
          block
          color="primary"
          size="large"
          className="login-btn"
          loading={loading}
          onClick={handleLogin}
        >
          登录
        </Button>
      </div>

      {/* 授权协议弹窗 */}
      <Popup
        visible={showAgreement}
        onMaskClick={() => setShowAgreement(false)}
        bodyStyle={{ borderRadius: '16px 16px 0 0', padding: '20px 20px 0' }}
      >
        <h3 style={{ margin: '0 0 12px', fontSize: 16, color: 'var(--text-primary, #e8eaf0)' }}>
          用户协议与数据授权声明
        </h3>
        <div className="agreement-content">
          <h4>一、数据使用说明</h4>
          <p>
            本应用（TradeMind AI）仅将您的交易数据用于本账户的复盘分析。
            所有分析均在服务器端完成，我们不会将您的交易数据出售、共享或用于任何商业目的。
          </p>
          <h4>二、数据范围</h4>
          <p>
            分析所用数据包括：历史成交记录（股票代码、买卖方向、价格、数量、时间），
            以及对应的市场行情数据。我们不采集您的姓名、身份证、银行账户等个人敏感信息。
          </p>
          <h4>三、数据安全</h4>
          <p>
            所有数据通过 HTTPS 加密传输。服务器数据存储于合规的云数据库，
            并采用访问控制、日志审计等安全措施。
          </p>
          <h4>四、您的权利</h4>
          <p>
            您可以随时停止使用本服务。如需删除账户数据，请联系客服，
            我们将在 7 个工作日内完成处理。
          </p>
          <h4>五、免责说明</h4>
          <p>
            本应用提供的复盘分析及建议仅供参考，不构成任何投资建议。
            投资有风险，入市需谨慎，最终投资决策由用户自行承担。
          </p>
        </div>
        <div style={{ padding: '16px 0' }}>
          <Button
            block
            color="primary"
            onClick={() => {
              setAgreed(true)
              setShowAgreement(false)
            }}
          >
            我已阅读，同意授权
          </Button>
          <Button
            block
            fill="none"
            style={{ marginTop: 8 }}
            onClick={() => setShowAgreement(false)}
          >
            暂不同意
          </Button>
        </div>
      </Popup>
    </div>
  )
}
