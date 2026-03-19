import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { UserProfile } from '../../types'

interface Props {
  profile: UserProfile
}

export default function PnlChart({ profile }: Props) {
  const option = useMemo(() => ({
    tooltip: {
      trigger: 'item' as const,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '10%',
      containLabel: true,
    },
    xAxis: {
      type: 'category' as const,
      data: ['总盈亏', '平均每笔', '最大单笔盈利', '最大单笔亏损'],
      axisLabel: { fontSize: 11 },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: {
        formatter: (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(0)}`,
      },
    },
    series: [
      {
        type: 'bar',
        data: [
          {
            value: profile.total_pnl,
            itemStyle: {
              color: profile.total_pnl >= 0 ? '#52c41a' : '#ff4d4f',
            },
          },
          {
            value: profile.avg_pnl_per_trade,
            itemStyle: {
              color: profile.avg_pnl_per_trade >= 0 ? '#52c41a' : '#ff4d4f',
            },
          },
          {
            value: profile.max_single_gain,
            itemStyle: { color: '#52c41a' },
          },
          {
            value: -Math.abs(profile.max_single_loss),
            itemStyle: { color: '#ff4d4f' },
          },
        ],
        barWidth: '50%',
      },
    ],
  }), [profile.total_pnl, profile.avg_pnl_per_trade, profile.max_single_gain, profile.max_single_loss])

  return (
    <ReactECharts
      option={option}
      style={{ height: 240 }}
      opts={{ renderer: 'svg' }}
    />
  )
}
