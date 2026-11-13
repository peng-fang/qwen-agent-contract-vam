import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const months = Array.from({ length: 13 }, (_, i) => `${i}月`)

function buildSeries() {
  const monthly = 7150
  const deposit = 14300
  const a: number[] = []
  const b: number[] = []
  const c: number[] = []
  for (let m = 0; m <= 12; m += 1) {
    a.push(Math.round(deposit + monthly * m))
    b.push(Math.round((deposit + monthly * m) * 1.02))
    c.push(Math.round(m < 6 ? deposit + monthly * m : deposit + monthly * 6))
  }
  return [
    { name: '港币转账（0% 手续费）', data: a },
    { name: '人民币微信（2% 手续费）', data: b },
    { name: '第 6 月提前退租（押金不退还）', data: c },
  ]
}

export function CashflowPage() {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    const series = buildSeries()
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: series.map((s) => s.name) },
      grid: { left: 60, right: 20, top: 50, bottom: 30 },
      xAxis: { type: 'category', data: months },
      yAxis: { type: 'value', name: '累计成本（港币）' },
      series: series.map((s) => ({
        name: s.name,
        type: 'line',
        smooth: true,
        data: s.data,
        areaStyle: { opacity: 0.08 },
      })),
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
  }, [])

  return (
    <Card>
      <CardHeader>
        <CardTitle>资金流时间线（示例）</CardTitle>
      </CardHeader>
      <CardContent>
        <div ref={ref} style={{ height: 420 }} />
        <p className="mt-3 text-sm text-muted-foreground">
          当前为演示数据：月租 7,150 港币 + 押金 14,300 港币；实际可接入后端 cashflow 接口。
        </p>
      </CardContent>
    </Card>
  )
}
