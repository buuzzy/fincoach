import { useRef, useEffect } from 'react'
import * as echarts from 'echarts'
import type { BacktestScenario, BacktestTradeDetail } from '../../types'
import { formatPnlValue } from '../../constants/accounts'

interface Props {
  scenario: BacktestScenario   // only the active scenario
}

const SCENARIO_COLOR = '#52c41a'
const ORIGINAL_COLOR = '#aaa'

export default function BacktestChart({ scenario }: Props) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)

  const details = (scenario.trade_details ?? []) as BacktestTradeDetail[]

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
      chartInstance.current = echarts.init(chartRef.current, undefined, { renderer: 'svg' })
    }

    const option: echarts.EChartsOption = {
      animation: true,
      tooltip: {
        trigger: 'axis',
        formatter: (params: unknown) => {
          if (!Array.isArray(params) || params.length === 0) return ''
          const idx = (params[0] as { dataIndex: number }).dataIndex
          const d = details[idx]
          return [
            `<b>${d?.stock ?? ''} ${labels[idx]}</b>`,
            `原始累计: <b style="color:${ORIGINAL_COLOR}">${formatPnlValue(cumulativeOriginal[idx])}</b>`,
            `${scenario.name}: <b style="color:${SCENARIO_COLOR}">${formatPnlValue(cumulativeAdjusted[idx])}</b>`,
          ].join('<br/>')
        },
      },
      legend: {
        data: ['原始', scenario.name],
        top: 4,
        textStyle: { fontSize: 11 },
        itemWidth: 14,
        itemHeight: 8,
      },
      grid: { left: 52, right: 12, top: 36, bottom: 36 },
      xAxis: {
        type: 'category',
        data: labels,
        boundaryGap: false,
        axisLabel: { fontSize: 10, interval: Math.floor(labels.length / 5) },
        axisLine: { lineStyle: { color: '#e0e0e0' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          fontSize: 10,
          formatter: (v: number) => {
            const abs = Math.abs(v)
            if (abs >= 10000) return `${v >= 0 ? '+' : ''}${(v / 10000).toFixed(0)}万`
            return `${v >= 0 ? '+' : ''}${v.toFixed(0)}`
          },
        },
        splitLine: { lineStyle: { color: '#f0f0f0' } },
      },
      series: [
        {
          name: '原始',
          type: 'line',
          data: cumulativeOriginal,
          lineStyle: { color: ORIGINAL_COLOR, width: 1.5, type: 'dashed' },
          itemStyle: { color: ORIGINAL_COLOR },
          symbol: 'none',
          smooth: true,
        } as echarts.SeriesOption,
        {
          name: scenario.name,
          type: 'line',
          data: cumulativeAdjusted,
          lineStyle: { color: SCENARIO_COLOR, width: 2.5 },
          itemStyle: { color: SCENARIO_COLOR },
          symbol: 'none',
          smooth: true,
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(82,196,26,0.18)' },
              { offset: 1, color: 'rgba(82,196,26,0)' },
            ]),
          },
        } as echarts.SeriesOption,
      ],
    }

    chartInstance.current.setOption(option, true)
  }, [scenario.name, labels.length])

  useEffect(() => {
    return () => {
      chartInstance.current?.dispose()
      chartInstance.current = null
    }
  }, [])

  if (labels.length === 0) return null

  return <div ref={chartRef} style={{ height: 200, width: '100%' }} />
}
