import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import type { PatternExampleBase } from '../../types'
import { getMarketData } from '../../services/api'

interface Props {
  example: PatternExampleBase
  aiCommentary: string
  active: boolean  // true when this slide is currently visible
}

export default function KLineCard({ example, aiCommentary, active }: Props) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const hasData = useRef(false)

  const stockCode = example.stock?.split(' ')[0] ?? ''
  const buyDate = example.buy_date ?? ''
  const sellDate = example.sell_date ?? ''
  const buyPrice = example.buy_price as number | undefined
  const sellPrice = example.sell_price as number | undefined

  // Resize when slide becomes visible
  useEffect(() => {
    if (active && chartInstance.current) {
      setTimeout(() => chartInstance.current?.resize(), 50)
    }
  }, [active])

  useEffect(() => {
    if (!stockCode || !buyDate || !sellDate) return

    const extendDate = (dateStr: string, days: number): string => {
      const d = new Date(dateStr)
      d.setDate(d.getDate() + days)
      return d.toISOString().slice(0, 10)
    }

    const startDate = extendDate(buyDate, -10)
    const endDate = extendDate(sellDate, 10)

    setLoading(true)
    setError(false)

    getMarketData(stockCode, startDate, endDate)
      .then((resp) => {
        if (!chartRef.current) return

        const bars = resp.bars
        const dates = bars.map((b) => b.date)
        const candleData = bars.map((b) => [b.open, b.close, b.low, b.high])

        if (!chartInstance.current) {
          chartInstance.current = echarts.init(chartRef.current, undefined, {
            renderer: 'svg',
          })
        }

        const markPointData: any[] = []

        if (buyDate && buyPrice !== undefined && dates.includes(buyDate)) {
          markPointData.push({
            name: '买入',
            coord: [buyDate, buyPrice],
            symbol: 'triangle',
            symbolSize: 16,
            itemStyle: { color: '#26a69a' },
            label: { formatter: '买', fontSize: 10, color: '#fff' },
          })
        }

        if (sellDate && sellPrice !== undefined && dates.includes(sellDate)) {
          markPointData.push({
            name: '卖出',
            coord: [sellDate, sellPrice],
            symbol: 'triangle',
            symbolRotate: 180,
            symbolSize: 16,
            itemStyle: { color: '#ef5350' },
            label: { formatter: '卖', fontSize: 10, color: '#fff' },
          })
        }

        const option: echarts.EChartsOption = {
          animation: false,
          grid: { top: 10, bottom: 30, left: 52, right: 10 },
          xAxis: {
            type: 'category',
            data: dates,
            axisLabel: {
              fontSize: 10,
              formatter: (val: string) => val.slice(5),
            },
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
        }

        chartInstance.current.setOption(option)
        hasData.current = true
        setLoading(false)

        // Resize once after data loads in case container was not yet sized
        setTimeout(() => chartInstance.current?.resize(), 80)
      })
      .catch(() => {
        setError(true)
        setLoading(false)
      })
  }, [stockCode, buyDate, sellDate, buyPrice, sellPrice])

  useEffect(() => {
    return () => {
      chartInstance.current?.dispose()
      chartInstance.current = null
    }
  }, [])

  return (
    <div className="kline-card-inner">
      {loading && (
        <div className="kline-skeleton">
          <span>加载行情中…</span>
        </div>
      )}
      {error && !loading && (
        <div className="kline-error">暂无行情数据</div>
      )}
      <div
        ref={chartRef}
        className="kline-chart-container"
        style={{ display: loading || error ? 'none' : 'block' }}
      />
      {aiCommentary && !loading && !error && (
        <div className="kline-ai-commentary">💡 {aiCommentary}</div>
      )}
    </div>
  )
}
