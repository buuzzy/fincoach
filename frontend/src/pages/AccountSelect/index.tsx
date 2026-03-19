import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { NavBar, Button, Swiper } from 'antd-mobile'
import { RightOutline } from 'antd-mobile-icons'
import {
  DndContext,
  closestCenter,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
  arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useAuth } from '../../contexts/AuthContext'
import { ACCOUNTS, ACCOUNT_MAP, formatPnl, type AccountInfo } from '../../constants/accounts'
import './index.css'

// ── 排序持久化 ────────────────────────────────────────────────────────────────

const STORAGE_KEY = 'tm_account_order'

function loadOrder(): number[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return ACCOUNTS.map((a) => a.userId)
    const parsed: number[] = JSON.parse(raw)
    const all = ACCOUNTS.map((a) => a.userId)
    const valid = parsed.filter((id) => all.includes(id))
    const missing = all.filter((id) => !valid.includes(id))
    return [...valid, ...missing]
  } catch {
    return ACCOUNTS.map((a) => a.userId)
  }
}

function saveOrder(order: number[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(order))
}

// ── 可拖拽排序项 ──────────────────────────────────────────────────────────────

function SortableItem({ account }: { account: AccountInfo }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: account.userId })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`sort-item${isDragging ? ' sort-dragging' : ''}`}
    >
      <div className="sort-item-logo" style={{ background: account.logoColor }}>
        {account.logoText}
      </div>
      <div className="sort-item-info">
        <div className="sort-item-broker">{account.brokerName}</div>
        <div className="sort-item-masked">{account.maskedAccount}</div>
      </div>
      <span className="sort-item-handle" {...attributes} {...listeners}>☰</span>
    </div>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────────────

export default function AccountSelect() {
  const navigate = useNavigate()
  const { logout } = useAuth()

  const [order, setOrder] = useState<number[]>(loadOrder)
  const [sortMode, setSortMode] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)

  const sortedAccounts = order
    .map((id) => ACCOUNT_MAP[id])
    .filter(Boolean) as AccountInfo[]

  const handleSelect = (userId: number) => {
    if (sortMode) return
    navigate(`/home/${userId}`)
  }

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 6 } }),
  )

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = order.indexOf(Number(active.id))
    const newIndex = order.indexOf(Number(over.id))
    const newOrder = arrayMove(order, oldIndex, newIndex)
    setOrder(newOrder)
    saveOrder(newOrder)
  }

  return (
    <div className="account-select-page">
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
        我的账户
      </NavBar>

      <div className="account-select-header">
        <p className="account-select-greeting">选择复盘账户</p>
        <p className="account-select-subtitle">左右滑动切换，长按拖动排序</p>
      </div>

      {/* ── Swiper 卡片区 ── */}
      {!sortMode && (
        <>
          <div className="account-swiper-wrap">
            <Swiper
              defaultIndex={0}
              onIndexChange={(i) => setActiveIndex(i)}
              indicator={() => null}
            >
              {sortedAccounts.map((account) => {
                const pnlPositive = account.totalPnl >= 0
                return (
                  <Swiper.Item key={account.userId}>
                    <div className="account-card" onClick={() => handleSelect(account.userId)}>
                      <div className="account-card-top">
                        <div className="broker-logo" style={{ background: account.logoColor }}>
                          {account.logoText}
                        </div>
                        <div className="account-card-enter"><RightOutline /></div>
                      </div>
                      <div className="account-broker-name">{account.brokerName}</div>
                      <div className="account-masked">交易账户：{account.maskedAccount}</div>
                      <div className="account-metrics">
                        <div className="account-metric">
                          <span className={`account-metric-val ${pnlPositive ? 'positive' : 'negative'}`}>
                            {formatPnl(account.totalPnl)}
                          </span>
                          <span className="account-metric-label">本期盈亏</span>
                        </div>
                        <div className="account-metric">
                          <span className="account-metric-val neutral">{account.winRate}%</span>
                          <span className="account-metric-label">胜率</span>
                        </div>
                        <div className="account-metric">
                          <span className="account-metric-val neutral">{account.tradePairs}笔</span>
                          <span className="account-metric-label">交易笔数</span>
                        </div>
                      </div>
                    </div>
                  </Swiper.Item>
                )
              })}
            </Swiper>
          </div>

          {/* 自定义小点指示器 */}
          <div className="account-dots">
            {sortedAccounts.map((_, i) => (
              <div key={i} className={`account-dot${i === activeIndex ? ' active' : ''}`} />
            ))}
          </div>
        </>
      )}

      {/* ── 排序模式 ── */}
      {sortMode && (
        <div className="sort-panel">
          <p className="sort-panel-hint">拖动右侧 ☰ 调整账户顺序</p>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <SortableContext items={order} strategy={verticalListSortingStrategy}>
              {sortedAccounts.map((account) => (
                <SortableItem key={account.userId} account={account} />
              ))}
            </SortableContext>
          </DndContext>
        </div>
      )}

      {/* ── 底部操作区 ── */}
      <div className="sort-toggle-row">
        <button className="sort-toggle-btn" onClick={() => setSortMode((v) => !v)}>
          {sortMode ? '✓ 完成排序' : '⇅ 调整顺序'}
        </button>
      </div>

      <div className="account-bottom">
        <Button block fill="outline" size="large" onClick={() => navigate('/history')}>
          查看历史报告
        </Button>
      </div>
    </div>
  )
}
