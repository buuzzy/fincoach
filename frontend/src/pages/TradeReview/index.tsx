import { useEffect, useState, useRef, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { NavBar, Tag, Collapse } from 'antd-mobile'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import { getTradeReview } from '../../services/api'
import GeneratingProgress from '../../components/GeneratingProgress'
import type { ProgressStep } from '../../components/GeneratingProgress'
import type { TradeReviewResponse } from '../../types'
import './index.css'

const REVIEW_STEPS: ProgressStep[] = [
  {
    label: '获取行情数据',
    detail: '读取持仓期间个股与大盘走势…',
    subSteps: [
      { text: '拉取个股持仓期间日 K 线数据', delayMs: 0 },
      { text: '拉取上证指数同期走势数据', delayMs: 500 },
      { text: '计算逐日涨跌幅与成交量变化', delayMs: 1200 },
    ],
    durationMs: 2000,
  },
  {
    label: '检索相关资讯',
    detail: '检索持仓期间新闻与公告…',
    subSteps: [
      { text: '检索个股持仓期间相关新闻', delayMs: 0 },
      { text: '匹配板块与行业动态资讯', delayMs: 600 },
      { text: '按时间线整理资讯摘要', delayMs: 1200 },
    ],
    durationMs: 4000,
  },
  {
    label: 'AI 情景还原',
    detail: '调用大模型还原交易情景…',
    subSteps: [
      { text: '构建交易情景上下文（K线 + 大盘 + 资讯）', delayMs: 0 },
      { text: '分析个股与大盘的相对强弱表现', delayMs: 2000 },
      { text: 'AI 生成买入背景与持仓过程分析', delayMs: 6000 },
      { text: 'AI 撰写卖出时点与交易结果总结', delayMs: 12000 },
    ],
    durationMs: 20000,
  },
]

function formatVolume(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(1) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v.toFixed(0)
}

export default function TradeReview() {
  const navigate = useNavigate()
  const { buyTradeId, sellTradeId } = useParams<{
    buyTradeId: string
    sellTradeId: string
  }>()

  const [review, setReview] = useState<TradeReviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const startedAtRef = useRef(Date.now())

  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!buyTradeId || !sellTradeId) return

    setLoading(true)
    setError(null)
    startedAtRef.current = Date.now()

    getTradeReview(Number(buyTradeId), Number(sellTradeId))
      .then(setReview)
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : '加载失败，请重试')
      })
      .finally(() => setLoading(false))
  }, [buyTradeId, sellTradeId])

  const renderChart = useCallback(() => {
    if (!review || review.kline.length === 0 || !chartRef.current) return

    const buyDate  = dayjs(review.buy_time).format('YYYY-MM-DD')
    const sellDate = dayjs(review.sell_time).format('YYYY-MM-DD')

    const dates      = review.kline.map((k) => k.date)
    const candleData = review.kline.map((k) => [k.open, k.close, k.low, k.high])

    const markPointData: echarts.MarkPointComponentOption['data'] = []

    if (dates.includes(buyDate)) {
      const idx = dates.indexOf(buyDate)
      markPointData!.push({
        name: '买入',
        coord: [buyDate, review.kline[idx].low],
        symbol: 'triangle',
        symbolSize: 16,
        symbolOffset: [0, 8],
        itemStyle: { color: '#26a69a' },
        label: { formatter: '买', fontSize: 10, color: '#fff' },
      })
    }

    if (dates.includes(sellDate)) {
      const idx = dates.indexOf(sellDate)
      markPointData!.push({
        name: '卖出',
        coord: [sellDate, review.kline[idx].high],
        symbol: 'triangle',
        symbolRotate: 180,
        symbolSize: 16,
        symbolOffset: [0, -8],
        itemStyle: { color: '#ef5350' },
        label: { formatter: '卖', fontSize: 10, color: '#fff' },
      })
    }

    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current, undefined, {
        renderer: 'svg',
      })
    }

    const option: echarts.EChartsOption = {
      animation: false,
      grid: { top: 10, bottom: 30, left: 52, right: 10 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { fontSize: 10, formatter: (val: string) => val.slice(5) },
        axisLine: { lineStyle: { color: '#e0e0e0' } },
        axisTick: { show: false },
      },
      yAxis: {
        scale: true,
        axisLabel: { fontSize: 10 },
        splitLine: { lineStyle: { color: '#f0f0f0' } },
      },
      series: [
        {
          type: 'candlestick',
          data: candleData,
          itemStyle: {
            color: '#ef5350',
            color0: '#26a69a',
            borderColor: '#ef5350',
            borderColor0: '#26a69a',
          },
          markPoint: { data: markPointData },
        },
      ],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
    }

    chartInstance.current.setOption(option, true)
    setTimeout(() => chartInstance.current?.resize(), 80)
  }, [review])

  useEffect(() => {
    renderChart()
  }, [renderChart])

  useEffect(() => {
    return () => {
      chartInstance.current?.dispose()
      chartInstance.current = null
    }
  }, [])

  const isProfit = (review?.pnl ?? 0) >= 0
  const pnlColor = isProfit ? 'var(--profit-color)' : 'var(--loss-color)'
  const pnlSign  = isProfit ? '+' : ''

  const holdingBars = review?.kline.filter((k) => {
    const buyDate  = dayjs(review.buy_time).format('YYYY-MM-DD')
    const sellDate = dayjs(review.sell_time).format('YYYY-MM-DD')
    return k.date >= buyDate && k.date <= sellDate
  }) ?? []

  return (
    <div className="trade-review-page">
      <NavBar onBack={() => navigate(-1)}>单笔交易复盘</NavBar>

      {(loading || error) && (
        <GeneratingProgress
          startedAt={startedAtRef.current}
          failed={!!error}
          failedReason={error ?? undefined}
          onRetry={() => navigate(-1)}
          steps={REVIEW_STEPS}
          title="正在生成单笔复盘"
          hint="通常需要 10～20 秒，请稍候…"
          failedTitle="复盘加载失败"
        />
      )}

      {!loading && !error && review && (
        <div className="tr-content">
          {/* ── 基本信息卡 ── */}
          <div className="tr-card tr-header-card">
            <div className="tr-stock-row">
              <span className="tr-stock-name">{review.stock_name}</span>
              <Tag color="default" fill="outline">{review.stock_code}</Tag>
            </div>
            <div className="tr-pnl-row">
              <span className="tr-pnl-amount" style={{ color: pnlColor }}>
                {isProfit ? `+¥${Math.abs(review.pnl).toFixed(2)}` : `-¥${Math.abs(review.pnl).toFixed(2)}`}
              </span>
              <span className="tr-pnl-pct" style={{ color: pnlColor }}>
                {pnlSign}{review.pnl_pct.toFixed(2)}%
              </span>
            </div>
            <div className="tr-meta-grid">
              <div className="tr-meta-item">
                <span className="tr-meta-label">买入</span>
                <span className="tr-meta-value">¥{review.buy_price.toFixed(2)}</span>
                <span className="tr-meta-sub">{dayjs(review.buy_time).format('MM/DD HH:mm')}</span>
              </div>
              <div className="tr-meta-item">
                <span className="tr-meta-label">卖出</span>
                <span className="tr-meta-value">¥{review.sell_price.toFixed(2)}</span>
                <span className="tr-meta-sub">{dayjs(review.sell_time).format('MM/DD HH:mm')}</span>
              </div>
              <div className="tr-meta-item">
                <span className="tr-meta-label">持仓</span>
                <span className="tr-meta-value">{review.hold_days} 天</span>
              </div>
              <div className="tr-meta-item">
                <span className="tr-meta-label">数量</span>
                <span className="tr-meta-value">{review.quantity.toLocaleString()} 股</span>
              </div>
            </div>
          </div>

          {/* ── K 线蜡烛图（默认展示） ── */}
          {review.kline.length > 0 && (
            <div className="tr-card">
              <h3 className="tr-section-title">持仓期间走势</h3>
              <div ref={chartRef} className="tr-kline-chart" />
            </div>
          )}

          {/* ── 逐日行情明细 + 资讯（可收起） ── */}
          <Collapse defaultActiveKey={[]}>
            {holdingBars.length > 0 && (
              <Collapse.Panel
                key="daily"
                title={`逐日行情明细（${holdingBars.length} 个交易日）`}
              >
                <div className="tr-daily-table-wrap">
                  <table className="tr-daily-table">
                    <thead>
                      <tr>
                        <th>日期</th>
                        <th>开盘</th>
                        <th>收盘</th>
                        <th>最高</th>
                        <th>最低</th>
                        <th>涨跌幅</th>
                        <th>成交量</th>
                      </tr>
                    </thead>
                    <tbody>
                      {holdingBars.map((k) => {
                        const chgPositive = k.change_pct >= 0
                        return (
                          <tr key={k.date}>
                            <td>{k.date.slice(5)}</td>
                            <td>{k.open.toFixed(2)}</td>
                            <td>{k.close.toFixed(2)}</td>
                            <td>{k.high.toFixed(2)}</td>
                            <td>{k.low.toFixed(2)}</td>
                            <td style={{ color: chgPositive ? '#ef5350' : '#26a69a' }}>
                              {chgPositive ? '+' : ''}{k.change_pct.toFixed(2)}%
                            </td>
                            <td>{formatVolume(k.volume)}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </Collapse.Panel>
            )}
            <Collapse.Panel key="news" title="持仓期间资讯">
              {review.news.length === 0 ? (
                <p className="tr-empty-text">持仓期间暂无相关资讯记录</p>
              ) : (
                <div className="tr-news-list">
                  {review.news.map((item, idx) => (
                    <div className="tr-news-item" key={idx}>
                      <div className="tr-news-meta">
                        <span className="tr-news-date">{item.publish_time}</span>
                      </div>
                      <p className="tr-news-title">{item.title}</p>
                      {item.summary && (
                        <p className="tr-news-summary">{item.summary.slice(0, 120)}…</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Collapse.Panel>
          </Collapse>

          {/* ── AI 情景还原 ── */}
          <div className="tr-card">
            <h3 className="tr-section-title">情景还原</h3>
            {review.status === 'failed' || !review.ai_review ? (
              <p className="tr-empty-text">AI 分析暂时不可用</p>
            ) : (
              <p className="tr-ai-review">{
                review.ai_review
                  .replace(/#{1,6}\s?/g, '')
                  .replace(/\*{1,2}([^*]+)\*{1,2}/g, '$1')
                  .replace(/^[-*]\s/gm, '')
              }</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
