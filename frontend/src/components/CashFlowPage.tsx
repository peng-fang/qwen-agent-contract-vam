import { useEffect, useRef, useState } from 'react'
import { Button } from './ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'
import { extractPayment, loadPayments, savePayments, workflowError, type PaymentPlan, type PaymentRecord } from '@/lib/workflows'

const inputClass = 'w-full rounded border bg-background px-2 py-2 text-sm'
function emptyPlan(title: string): PaymentPlan {
  return { title, currency: 'CNY', payer: '付款方', confirmed: false, origin: 'user', installments: [{ due_date: '', amount: '', label: '付款' }] }
}

function PaymentChart({ comparison }: { comparison: PaymentRecord['comparison'] }) {
  const container = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let disposed = false
    let cleanup = () => {}
    Promise.all([import('echarts/core'), import('echarts/charts'), import('echarts/components'), import('echarts/renderers')]).then(([core, charts, components, renderers]) => {
      if (disposed || !container.current) return
      core.use([charts.LineChart, components.GridComponent, components.TooltipComponent, components.LegendComponent, renderers.CanvasRenderer])
      const chart = core.init(container.current)
      chart.setOption({ tooltip: { trigger: 'axis' }, legend: { type: 'scroll', bottom: 0 }, grid: { left: 65, right: 20, top: 25, bottom: 80 },
        xAxis: { type: 'category', data: comparison.dates }, yAxis: { type: 'value', name: comparison.currency },
        series: comparison.plans.map((plan) => ({ name: plan.title, type: 'line', step: 'end',
          data: plan.points.map((point) => Number(point.cumulative)) })) })
      const observer = new ResizeObserver(() => chart.resize())
      observer.observe(container.current)
      cleanup = () => { observer.disconnect(); chart.dispose() }
    })
    return () => { disposed = true; cleanup() }
  }, [comparison])
  return <div ref={container} className="h-80 w-full" role="img" aria-label="各付款计划的累计支出阶梯曲线，精确金额见下方表格" />
}

export function CashFlowPage() {
  const [plans, setPlans] = useState<PaymentPlan[]>([emptyPlan('一次付清'), emptyPlan('分期付款')])
  const [record, setRecord] = useState<PaymentRecord | null>(null)
  const [dirty, setDirty] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [draftNotes, setDraftNotes] = useState<Record<number, string>>({})
  const [draftFile, setDraftFile] = useState<File | null>(null)
  const [draftIndex, setDraftIndex] = useState(0)
  function edit(index: number, next: PaymentPlan, fromModel = false) {
    setPlans((current) => current.map((p, i) => i === index ? { ...next, origin: fromModel ? 'contract_draft' : 'user', confirmed: false } : p))
    setDirty(true)
  }
  async function save() {
    setBusy('save'); setError('')
    try {
      const data = await savePayments(plans, record)
      setRecord(data); setPlans(data.plans); setDirty(false)
      localStorage.setItem('last-payment-plan', data.id)
    } catch (e) { setError(workflowError(e)) } finally { setBusy('') }
  }
  async function restore() {
    setBusy('restore'); setError('')
    try {
      const id = localStorage.getItem('last-payment-plan')
      if (!id) throw new Error('还没有保存的付款计划')
      const data = await loadPayments(id)
      setRecord(data); setPlans(data.plans); setDirty(false); setDraftNotes({})
    } catch (e) { setError(workflowError(e)) } finally { setBusy('') }
  }
  async function extract() {
    if (!draftFile) { setError('请先选择合同文件'); return }
    setBusy('extract'); setError('')
    try {
      const data = await extractPayment(draftFile)
      const draft: PaymentPlan = { ...data, currency: data.currency ?? '', payer: data.payer ?? '', confirmed: false,
        installments: data.installments.map((item) => ({ ...item, due_date: item.due_date ?? '', amount: item.amount == null ? '' : String(item.amount) })) }
      edit(draftIndex, draft, true)
      setDraftNotes((current) => ({ ...current, [draftIndex]: data.missing.length ? `待补充：${data.missing.join('、')}` : '模型草稿，请逐期核对后确认。' }))
    } catch (e) { setError(workflowError(e)) } finally { setBusy('') }
  }
  function example() {
    setRecord(null); setDirty(true); setDraftNotes({}); setError('')
    const first = { ...emptyPlan('一次付清'), installments: [{ due_date: '2027-01-01', amount: '12000', label: '全款' }] }
    const second = { ...emptyPlan('三期付款'), installments: ['01', '02', '03'].map((m) => ({ due_date: `2027-${m}-01`, amount: '4000', label: '分期付款' })) }
    setPlans([first, second])
  }
  return <div className="space-y-5">
    <Card><CardHeader><CardTitle>付款计划与现金流</CardTitle></CardHeader><CardContent className="space-y-3">
      <p className="text-sm text-muted-foreground">比较同一付款方、同一币种的时间安排。模型只提取草稿；金额和日期经确认后由程序计算，不自动假设利息或汇率。</p>
      <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={example} disabled={!!busy}>填入一次付清／三期示例</Button>
        <Button variant="outline" onClick={() => void restore()} disabled={!!busy}>恢复上次计划</Button></div>
      <fieldset disabled={!!busy} className="flex flex-wrap items-center gap-2 border-t pt-3">
        <label className="text-sm">合同文件<input aria-label="提取付款计划的合同" type="file" accept=".pdf,.docx,.txt,.md" className="block max-w-full" onChange={(e) => setDraftFile(e.target.files?.[0] ?? null)} /></label>
        <label className="text-sm">导入到<select className={inputClass} value={draftIndex} onChange={(e) => setDraftIndex(Number(e.target.value))}>{plans.map((p, i) => <option key={i} value={i}>方案{i + 1}：{p.title}</option>)}</select></label>
        <Button variant="outline" onClick={() => void extract()}>{busy === 'extract' ? '提取中…' : '从合同提取草稿'}</Button>
      </fieldset>
    </CardContent></Card>
    <form onSubmit={(e) => { e.preventDefault(); void save() }} className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-2">{plans.map((plan, index) => <Card key={index}>
        <CardHeader><CardTitle>方案 {index + 1}</CardTitle></CardHeader><CardContent className="space-y-3">
          <fieldset disabled={!!busy} className="space-y-3">
            <label className="block text-sm">名称<input required className={inputClass} value={plan.title} onChange={(e) => edit(index, { ...plan, title: e.target.value })} /></label>
            <div className="grid grid-cols-2 gap-2"><label className="text-sm">币种<select className={inputClass} required value={plan.currency} onChange={(e) => edit(index, { ...plan, currency: e.target.value })}><option value="">请选择</option><option>CNY</option><option>HKD</option><option>USD</option></select></label>
              <label className="text-sm">付款方<input required className={inputClass} value={plan.payer} onChange={(e) => edit(index, { ...plan, payer: e.target.value })} /></label></div>
            {draftNotes[index] && <p className="text-sm text-amber-800">{draftNotes[index]}</p>}
            {plan.installments.map((item, n) => <div key={n} className="grid gap-2 rounded border p-2 sm:grid-cols-2">
              <label className="text-sm">第{n + 1}期日期<input required type="date" className={inputClass} value={item.due_date} onChange={(e) => edit(index, { ...plan, installments: plan.installments.map((v, i) => i === n ? { ...v, due_date: e.target.value } : v) })} /></label>
              <label className="text-sm">金额<input required type="number" min="0" step=".01" className={inputClass} value={item.amount} onChange={(e) => edit(index, { ...plan, installments: plan.installments.map((v, i) => i === n ? { ...v, amount: e.target.value } : v) })} /></label>
              <label className="text-sm">项目<input required className={inputClass} value={item.label} onChange={(e) => edit(index, { ...plan, installments: plan.installments.map((v, i) => i === n ? { ...v, label: e.target.value } : v) })} /></label>
              <Button type="button" variant="ghost" disabled={plan.installments.length === 1} onClick={() => edit(index, { ...plan, installments: plan.installments.filter((_, i) => i !== n) })}>删除此期</Button>
            </div>)}
            <Button type="button" variant="outline" disabled={plan.installments.length >= 120} onClick={() => edit(index, { ...plan, installments: [...plan.installments, { due_date: '', amount: '', label: '付款' }] })}>增加一期</Button>
            {!!plan.sources?.length && <details className="text-sm"><summary>查看参考原文：{plan.source_filename}（{plan.origin === 'user' ? '计划经用户编辑' : '模型提取草稿'}）</summary>{plan.sources.map((s, i) => <blockquote className="my-2 border-l pl-2" key={i}>第{s.page}页：{s.quote}</blockquote>)}</details>}
            <label className="flex gap-2 text-sm"><input type="checkbox" required checked={plan.confirmed} onChange={(e) => { setPlans((current) => current.map((p, i) => i === index ? { ...p, confirmed: e.target.checked } : p)); setDirty(true) }} />我已核对本方案的付款方、币种、日期和金额</label>
          </fieldset>
        </CardContent></Card>)}</div>
      <Button disabled={!!busy} type="submit">{busy === 'save' ? '计算中…' : '保存并计算对比'}</Button>
    </form>
    {error && <p role="alert" className="rounded border p-3 text-sm text-red-700">{error}</p>}
    {record && <Card><CardHeader><CardTitle>付款时间表与累计支出</CardTitle></CardHeader><CardContent className="space-y-3">
      {dirty ? <p className="text-sm text-amber-800">计划已编辑，下列是版本{record.revision}的已保存结果；请重新确认并计算。</p> : <p className="text-sm">版本{record.revision} · 已保存历史版本{record.history.length}个 · {record.comparison.payer} · {record.comparison.currency}</p>}
      <PaymentChart comparison={record.comparison} />
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="text-left">每个日期显示：当期支出／累计支出</caption><thead><tr><th className="p-2">日期</th>{record.comparison.plans.map((p, i) => <th className="p-2" key={i}>{p.title}</th>)}</tr></thead><tbody>
        {record.comparison.dates.map((day, i) => <tr key={day}><td className="border-t p-2">{day}</td>{record.comparison.plans.map((p, n) => <td className="border-t p-2 tabular-nums" key={n}>{p.points[i].payment}／{p.points[i].cumulative}</td>)}</tr>)}
        <tr><th className="border-t p-2">总支出</th>{record.comparison.plans.map((p, i) => <td className="border-t p-2" key={i}>{p.total}</td>)}</tr>
      </tbody></table></div>
    </CardContent></Card>}
  </div>
}
