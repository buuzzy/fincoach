import { useRef, useEffect } from 'react'
import * as echarts from 'echarts'
import type { BacktestScenario, BacktestTradeDetail } from '../../types'

interface Props {
  scenarios: BacktestScenario[]
  bestScenario: string
  activeScenario?: string  // currently focused in swiper
}

// Colour palette for scenarios (first = best always highlighted)
const SCENARIO_COLORS = ['#52c41a', '#1677ff', '#fa8c16', '#722ed1', '#13c2c2']
const ORIGINAL_COLOR = '#aaa'

export default function BacktestChart({ scenarios, bestScenario, activeScenario }: Props) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)

  // Use trade_details from best scenario for x-axis labels (most complete set)
  const base = scenarios.find((s) => s.name === bestScenario) ?? scenarios[0]
  if (!base) return null

  const details = (base.trade_details ?? []) as BacktestTradeDetail[]
  if (details.length === 0) return null

  const labels = details.map((d) => d.sell_date?.slice(5) ?? '')

  // Build cumulative original (same for all scenarios since same trades)
  const cumulativeOriginal: number[] = []
  let sumOrig = 0
  details.forEach((d) => {
    sumOrig += d.original_pnl
    cumulativeOriginal.push(Math.round(sumOrig * 100) / 100)
  })

  // Build cumulative adjusted for each scenario
  // Each scenario may have different trade_details ordering — rebuild by matching sell_date
  const scenarioCumulatives = scenarios.map((s) => {
    const detailMap = new Map<string, number>()
    ;(s.trade_details as BacktestTradeDetail[]).forEach((d) => {
      const key = `${d.stock}|${d.sell_date}`
      detailMap.set(key, d.adjusted_pnl)
    })
    let sum = 0
    return details.map((d) => {
      const key = `${d.stock}|${d.sell_date}`
      const adj = detailMap.has(key) ? detailMap.get(key)! : d.original_pnl
      sum += adj
      return Math.round(sum * 100) / 100
    })
  })

  useEffect(() => {
    if (!chartRef.current || labels.length === 0) return

    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current, undefined, { renderer: 'svg' })
    }

    const active = activeScenario ?? bestScenario

    const scenarioSeries: echarts.SeriesOption[] = scenarios.map((s, i) => {
      const color = SCENARIO_COLORS[i % SCENARIO_COLORS.length]
      const isActive = s.name === active
      return {
        name: s.name,
        type: 'line',
        data: scenarioCumulatives[i],
        lineStyle: {
          color,
          width: isActive ? 2.5 : 1.5,
          type: isActive ? 'solid' : 'dashed',
          opacity: isActive ? 1 : 0.45,
        },
        itemStyle: { color },
        symbol: 'none',
        smooth: true,
        z: isActive ? 10 : 5,
      } as echarts.SeriesOption
    })

    const option: echarts.EChartsOption = {
      animation: false,
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          if (!Array.isArray(params) || params.length === 0) return ''
          const idx = params[0].dataIndex
          const d = details[idx]
          const lines = [`<b>${d?.stock ?? ''} ${labels[idx]}</b>`]
          lines.push(
            `原始累计: <b style="color:${ORIGINAL_COLOR}">${cumulativeOriginal[idx] >= 0 ? '+' : ''}${cumulativeOriginal[idx].toFixed(0)}</b>`
          )
          scenarios.forEach((s, i) => {
            const color = SCENARIO_COLORS[i % SCENARIO_COLORS.length]
            const val = scenarioCumulatives[i][idx]
            lines.push(
              `${s.name}: <b style="color:${color}">${val >= 0 ? '+' : ''}${val.toFixed(0)}</b>`
            )
          })
          return lines.join('<br/>')
        },
      },
      legend: {
        data: ['原始', ...scenarios.map((s) => s.name)],
        top: 4,
        textStyle: { fontSize: 10 },
        itemWidth: 14,
        itemHeight: 8,
      },
      grid: { left: 52, right: 12, top: 46, bottom: 36 },
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
          formatter: (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(0)}`,
        },
        splitLine: { lineStyle: { color: '#f0f0f0' } },
      },
      series: [
        {
          name: '原始',
          type: 'line',
          data: cumulativeOriginal,
          lineStyle: { color: ORIGINAL_COLOR, width: 1.5, type: 'dotted' },
          itemStyle: { color: ORIGINAL_COLOR },
          symbol: 'none',
          smooth: true,
          z: 1,
        } as echarts.SeriesOption,
        ...scenarioSeries,
      ],
    }

    chartInstance.current.setOption(option, true)
  }, [activeScenario, labels.length])

  useEffect(() => {
    return () => {
      chartInstance.current?.dispose()
      chartInstance.current = null
    }
  }, [])

  return <div ref={chartRef} style={{ height: 220, width: '100%' }} />
}
