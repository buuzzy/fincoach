import { useEffect, useState, useRef, useCallback, useMemo } from 'react'
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

interface AiSection {
  title: string
  content: string
}

function parseAiSections(raw: string): AiSection[] {
  const cleaned = raw
    .replace(/#{1,6}\s?/g, '')
    .replace(/\*{1,2}([^*]+)\*{1,2}/g, '$1')
    .replace(/^[-*]\s/gm, '')

  const parts = cleaned.split(/(?=【[^】]+】)/).filter(s => s.trim())
  if (parts.length === 0) return [{ title: '情景还原', content: cleaned.trim() }]

  return parts.map(part => {
    const match = part.match(/^【([^】]+)】(.*)$/s)
    if (match) return { title: match[1], content: match[2].trim() }
    return { title: '', content: part.trim() }
  }).filter(s => s.content)
}

function formatVolume(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(1) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v.toFixed(0)
}

function FloatPnlChart({ holdingBars, buyPrice }: {
  holdingBars: { date: string; close: number; low: number; high: number }[]
  buyPrice: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const inst = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current || holdingBars.length === 0) return

    const dates = holdingBars.map(k => k.date.slice(5))
    const pctData = holdingBars.map(k =>
      +((k.close - buyPrice) / buyPrice * 100).toFixed(2)
    )

    let maxIdx = 0, minIdx = 0
    pctData.forEach((v, i) => {
      if (v > pctData[maxIdx]) maxIdx = i
      if (v < pctData[minIdx]) minIdx = i
    })

    if (!inst.current) {
      inst.current = echarts.init(ref.current, undefined, { renderer: 'svg' })
    }

    inst.current.setOption({
      animation: true,
      grid: { top: 24, bottom: 28, left: 48, right: 12 },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLabel: { fontSize: 10 },
        axisLine: { lineStyle: { color: '#e0e0e0' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: { fontSize: 10, formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#f0f0f0' } },
      },
      series: [{
        type: 'line',
        data: pctData,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2.5, color: '#5b8ff9' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(91,143,249,0.22)' },
            { offset: 1, color: 'rgba(91,143,249,0)' },
          ]),
        },
        markPoint: {
          symbol: 'circle',
          symbolSize: 8,
          label: { fontSize: 10, formatter: (p: { value: number }) => (p.value >= 0 ? '+' : '') + p.value + '%' },
          data: [
            {
              coord: [dates[maxIdx], pctData[maxIdx]],
              value: pctData[maxIdx],
              itemStyle: { color: '#26a69a' },
              label: { position: 'top' },
            },
            {
              coord: [dates[minIdx], pctData[minIdx]],
              value: pctData[minIdx],
              itemStyle: { color: '#ef5350' },
              label: { position: 'bottom' },
            },
          ],
        },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { type: 'dashed', color: '#ccc' },
          data: [{ yAxis: 0 }],
          label: { show: false },
        },
      }],
      tooltip: {
        trigger: 'axis',
        formatter: (params: echarts.DefaultLabelFormatterCallbackParams[]) => {
          const p = params[0]
          const v = p.value as number
          const color = v >= 0 ? '#ef5350' : '#26a69a'
          return `<b>${p.name}</b><br/>浮盈浮亏: <span style="color:${color}">${v >= 0 ? '+' : ''}${v}%</span>`
        },
      },
    }, true)

    setTimeout(() => inst.current?.resize(), 80)
    return () => { inst.current?.dispose(); inst.current = null }
  }, [holdingBars, buyPrice])

  return <div ref={ref} className="tr-inline-chart" />
}

function VsIndexChart({ holdingBars, indexKline, sectorKline, sectorName, buyDate, sellDate }: {
  holdingBars: { date: string; close: number }[]
  indexKline: { date: string; close: number }[]
  sectorKline: { date: string; close: number }[]
  sectorName: string
  buyDate: string
  sellDate: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const inst = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current || holdingBars.length === 0) return

    const idxHolding = indexKline.filter(k => k.date >= buyDate && k.date <= sellDate)
    if (idxHolding.length === 0) return

    const baseStock = holdingBars[0].close
    const baseIdx = idxHolding[0].close

    const dates = holdingBars.map(k => k.date.slice(5))
    const stockPct = holdingBars.map(k =>
      +((k.close - baseStock) / baseStock * 100).toFixed(2)
    )
    const idxPct = idxHolding.map(k =>
      +((k.close - baseIdx) / baseIdx * 100).toFixed(2)
    )

    const legendData: { name: string; icon: string }[] = [
      { name: '个股', icon: 'roundRect' },
      { name: '上证指数', icon: 'roundRect' },
    ]

    const series: echarts.SeriesOption[] = [
      {
        name: '个股',
        type: 'line',
        data: stockPct,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2.5, color: '#5b8ff9' },
        itemStyle: { color: '#5b8ff9' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(91,143,249,0.15)' },
            { offset: 1, color: 'rgba(91,143,249,0)' },
          ]),
        },
      },
      {
        name: '上证指数',
        type: 'line',
        data: idxPct,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.5, color: '#aaa', type: 'dashed' },
        itemStyle: { color: '#aaa' },
      },
    ]

    const sectHolding = sectorKline.filter(k => k.date >= buyDate && k.date <= sellDate)
    if (sectHolding.length > 0) {
      const baseSect = sectHolding[0].close
      const sectPct = sectHolding.map(k =>
        +((k.close - baseSect) / baseSect * 100).toFixed(2)
      )
      const label = sectorName || '板块'
      legendData.push({ name: label, icon: 'roundRect' })
      series.push({
        name: label,
        type: 'line',
        data: sectPct,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color: '#ff9845' },
        itemStyle: { color: '#ff9845' },
      })
    }

    if (!inst.current) {
      inst.current = echarts.init(ref.current, undefined, { renderer: 'svg' })
    }

    inst.current.setOption({
      animation: true,
      grid: { top: 32, bottom: 28, left: 48, right: 12 },
      legend: {
        top: 4,
        textStyle: { fontSize: 11 },
        itemWidth: 14,
        itemHeight: 8,
        data: legendData,
      },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLabel: { fontSize: 10 },
        axisLine: { lineStyle: { color: '#e0e0e0' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: { fontSize: 10, formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#f0f0f0' } },
      },
      series,
      tooltip: {
        trigger: 'axis',
        formatter: (params: echarts.DefaultLabelFormatterCallbackParams[]) => {
          let s = `<b>${params[0].name}</b>`
          params.forEach(p => {
            const v = p.value as number
            const color = v >= 0 ? '#ef5350' : '#26a69a'
            s += `<br/>${p.seriesName}: <span style="color:${color}">${v >= 0 ? '+' : ''}${v}%</span>`
          })
          return s
        },
      },
    }, true)

    setTimeout(() => inst.current?.resize(), 80)
    return () => { inst.current?.dispose(); inst.current = null }
  }, [holdingBars, indexKline, sectorKline, sectorName, buyDate, sellDate])

  return <div ref={ref} className="tr-inline-chart" />
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

  const buyDate  = review ? dayjs(review.buy_time).format('YYYY-MM-DD') : ''
  const sellDate = review ? dayjs(review.sell_time).format('YYYY-MM-DD') : ''

  const holdingBars = useMemo(() =>
    review?.kline.filter(k => k.date >= buyDate && k.date <= sellDate) ?? [],
    [review, buyDate, sellDate],
  )

  const aiSections = useMemo(() =>
    review?.ai_review ? parseAiSections(review.ai_review) : [],
    [review],
  )

  const getSection = (title: string) =>
    aiSections.find(s => s.title.includes(title))

  const renderChart = useCallback(() => {
    if (!review || review.kline.length === 0 || !chartRef.current) return

    const dates      = review.kline.map(k => k.date)
    const candleData = review.kline.map(k => [k.open, k.close, k.low, k.high])
    const volData    = review.kline.map(k => ({
      value: k.volume,
      itemStyle: { color: k.close >= k.open ? 'rgba(239,83,80,0.4)' : 'rgba(38,166,154,0.4)' },
    }))

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

    chartInstance.current.setOption({
      animation: true,
      grid: [
        { top: 10, bottom: '28%', left: 52, right: 10 },
        { top: '78%', bottom: 30, left: 52, right: 10 },
      ],
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      xAxis: [
        {
          type: 'category',
          data: dates,
          gridIndex: 0,
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          type: 'category',
          data: dates,
          gridIndex: 1,
          axisLabel: { fontSize: 10, formatter: (val: string) => val.slice(5) },
          axisLine: { lineStyle: { color: '#e0e0e0' } },
          axisTick: { show: false },
        },
      ],
      yAxis: [
        {
          scale: true,
          gridIndex: 0,
          axisLabel: { fontSize: 10 },
          splitLine: { lineStyle: { color: '#f0f0f0' } },
        },
        {
          gridIndex: 1,
          axisLabel: { show: false },
          splitLine: { show: false },
          axisTick: { show: false },
          axisLine: { show: false },
        },
      ],
      series: [
        {
          type: 'candlestick',
          data: candleData,
          xAxisIndex: 0,
          yAxisIndex: 0,
          itemStyle: {
            color: '#ef5350',
            color0: '#26a69a',
            borderColor: '#ef5350',
            borderColor0: '#26a69a',
          },
          markPoint: { data: markPointData },
        },
        {
          type: 'bar',
          data: volData,
          xAxisIndex: 1,
          yAxisIndex: 1,
          barWidth: '60%',
        },
      ],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: unknown) => {
          if (!Array.isArray(params) || params.length === 0) return ''
          const idx = (params[0] as { dataIndex: number }).dataIndex
          const k = review.kline[idx]
          const chgColor = k.change_pct >= 0 ? '#ef5350' : '#26a69a'
          return [
            `<b>${k.date.slice(5)}</b>`,
            `开: ${k.open.toFixed(2)}  收: ${k.close.toFixed(2)}`,
            `高: ${k.high.toFixed(2)}  低: ${k.low.toFixed(2)}`,
            `量: ${formatVolume(k.volume)}`,
            `<span style="color:${chgColor}">${k.change_pct >= 0 ? '+' : ''}${k.change_pct.toFixed(2)}%</span>`,
          ].join('<br/>')
        },
      },
    }, true)

    setTimeout(() => chartInstance.current?.resize(), 80)
  }, [review, buyDate, sellDate])

  useEffect(() => { renderChart() }, [renderChart])

  useEffect(() => {
    return () => { chartInstance.current?.dispose(); chartInstance.current = null }
  }, [])

  const isProfit = (review?.pnl ?? 0) >= 0
  const pnlColor = isProfit ? 'var(--profit-color)' : 'var(--loss-color)'
  const pnlSign  = isProfit ? '+' : ''

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

          {/* ── K 线蜡烛图 ── */}
          {review.kline.length > 0 && (
            <div className="tr-card">
              <h3 className="tr-section-title">持仓期间走势</h3>
              <div ref={chartRef} className="tr-kline-chart" />
            </div>
          )}

          {/* ── AI 情景还原（图文交替） ── */}
          <div className="tr-card">
            <h3 className="tr-section-title">情景还原</h3>
            {review.status === 'failed' || !review.ai_review ? (
              <p className="tr-empty-text">AI 分析暂时不可用</p>
            ) : (
              <div className="tr-ai-review">
                {/* 买入时点 */}
                {getSection('买入') && (
                  <div className="tr-ai-section">
                    <h4 className="tr-ai-heading">{getSection('买入')!.title}</h4>
                    <p className="tr-ai-text">{getSection('买入')!.content}</p>
                  </div>
                )}

                {/* 持仓历程 */}
                {getSection('持仓') && (
                  <div className="tr-ai-section">
                    <h4 className="tr-ai-heading">{getSection('持仓')!.title}</h4>
                    <p className="tr-ai-text">{getSection('持仓')!.content}</p>
                  </div>
                )}

                {/* 浮盈浮亏曲线 */}
                {holdingBars.length > 1 && (
                  <div className="tr-ai-chart-block">
                    <span className="tr-ai-chart-label">持仓浮盈浮亏</span>
                    <FloatPnlChart holdingBars={holdingBars} buyPrice={review.buy_price} />
                  </div>
                )}

                {/* 卖出时点 */}
                {getSection('卖出') && (
                  <div className="tr-ai-section">
                    <h4 className="tr-ai-heading">{getSection('卖出')!.title}</h4>
                    <p className="tr-ai-text">{getSection('卖出')!.content}</p>
                  </div>
                )}

                {/* 个股 vs 大盘 vs 板块对比 */}
                {holdingBars.length > 1 && review.index_kline.length > 0 && (
                  <div className="tr-ai-chart-block">
                    <span className="tr-ai-chart-label">
                      个股 vs 大盘{review.sector_name ? ` vs ${review.sector_name}` : ''}
                    </span>
                    <VsIndexChart
                      holdingBars={holdingBars}
                      indexKline={review.index_kline}
                      sectorKline={review.sector_kline ?? []}
                      sectorName={review.sector_name ?? '板块'}
                      buyDate={buyDate}
                      sellDate={sellDate}
                    />
                  </div>
                )}

                {/* 交易复盘 */}
                {getSection('复盘') && (
                  <div className="tr-ai-section">
                    <h4 className="tr-ai-heading">{getSection('复盘')!.title}</h4>
                    <p className="tr-ai-text">{getSection('复盘')!.content}</p>
                  </div>
                )}

                {/* 容错：无法按【】拆分时直接渲染全部文字 */}
                {aiSections.length === 1 && !aiSections[0].title.includes('买入') && (
                  <div className="tr-ai-section">
                    <p className="tr-ai-text">{aiSections[0].content}</p>
                  </div>
                )}
              </div>
            )}
          </div>

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
        </div>
      )}
    </div>
  )
}
