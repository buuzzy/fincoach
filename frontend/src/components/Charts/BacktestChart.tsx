import { useRef, useEffect } from 'react'
import * as echarts from 'echarts'
import type { BacktestScenario, BacktestTradeDetail } from '../../types'

interface Props {
  scenarios: BacktestScenario[]
  bestScenario: string
}

export default function BacktestChart({ scenarios, bestScenario }: Props) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)

  const best = scenarios.find((s) => s.name === bestScenario) ?? scenarios[0]
  if (!best) return null

  const details = (best.trade_details ?? []) as BacktestTradeDetail[]

  // Build cumulative P&L
  const labels: string[] = []
  const cumulativeOriginal: number[] = []
  const cumulativeAdjusted: number[] = []

  let sumOrig = 0
  let sumAdj = 0
  details.forEach((d) => {
    sumOrig += d.original_pnl
    sumAdj += d.adjusted_pnl
    labels.push(d.sell_date?.slice(5) ?? '')
    cumulativeOriginal.push(Math.round(sumOrig * 100) / 100)
    cumulativeAdjusted.push(Math.round(sumAdj * 100) / 100)
  })

  useEffect(() => {
    if (!chartRef.current || labels.length === 0) return

    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current, undefined, {
        renderer: 'svg',
      })
    }

    const option: echarts.EChartsOption = {
      animation: false,
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          if (!Array.isArray(params) || params.length === 0) return ''
          const idx = params[0].dataIndex
          const orig = cumulativeOriginal[idx]
          const adj = cumulativeAdjusted[idx]
          const d = details[idx]
          return [
            `<b>${d?.stock ?? ''} ${labels[idx]}</b>`,
            `原始累计: <b style="color:#1677ff">${orig >= 0 ? '+' : ''}${orig.toFixed(2)}</b>`,
            `最优累计: <b style="color:#52c41a">${adj >= 0 ? '+' : ''}${adj.toFixed(2)}</b>`,
          ].join('<br/>')
        },
      },
      legend: {
        data: ['原始累计', '最优累计'],
        top: 4,
        textStyle: { fontSize: 11 },
      },
      grid: { left: 52, right: 12, top: 36, bottom: 36 },
      xAxis: {
        type: 'category',
        data: labels,
        boundaryGap: false,
        axisLabel: {
          fontSize: 10,
          interval: Math.floor(labels.length / 5),
        },
        axisLine: { lineStyle: { color: '#e0e0e0' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          fontSize: 10,
          formatter: (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(0)}`,
        },
        splitLine: { lineStyle: { color: '#f0f0f0' } },
      },
      series: [
        {
          name: '原始累计',
          type: 'line',
          data: cumulativeOriginal,
          lineStyle: { color: '#1677ff', width: 2 },
          itemStyle: { color: '#1677ff' },
          symbol: 'none',
          smooth: true,
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(22,119,255,0.15)' },
              { offset: 1, color: 'rgba(22,119,255,0)' },
            ]),
          },
        },
        {
          name: '最优累计',
          type: 'line',
          data: cumulativeAdjusted,
          lineStyle: { color: '#52c41a', width: 2 },
          itemStyle: { color: '#52c41a' },
          symbol: 'none',
          smooth: true,
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(82,196,26,0.15)' },
              { offset: 1, color: 'rgba(82,196,26,0)' },
            ]),
          },
        },
      ],
    }

    chartInstance.current.setOption(option)
  }, [labels.length])

  useEffect(() => {
    return () => {
      chartInstance.current?.dispose()
      chartInstance.current = null
    }
  }, [])

  return (
    <div ref={chartRef} style={{ height: 220, width: '100%' }} />
  )
}
