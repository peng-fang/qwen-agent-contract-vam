import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { checklistError, estimateConsequence, fieldClass, type ConsequenceTemplate, type Estimate } from '@/lib/checklist'

const fields = {
  lease_exit: [['deposit', '押金'], ['penalty', '违约金']],
  repurchase: [['principal', '回购本金'], ['annual_rate', '年利率（%）'],
    ['years', '计息期限（整年）'], ['offset', '抵扣金额（没有则填 0）']],
}
const money = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 2 })

export function ChecklistEstimate({ template }: { template: ConsequenceTemplate }) {
  const [parameters, setParameters] = useState<Record<string, string | boolean>>({})
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [rows, setRows] = useState<Estimate[]>([])
  const [error, setError] = useState('')

  async function run(e: FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      setRows(await estimateConsequence(template, {
        ...parameters, ...(template === 'lease_exit' ? { early_exit_applies: confirm } : {}),
      }))
    } catch (error) { setError(checklistError(error)) } finally { setBusy(false) }
  }

  const update = (key: string, value: string) => {
    setParameters((current) => ({ ...current, [key]: value }))
    setRows([])
  }

  return <details className="rounded-lg border bg-background px-3">
    <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium text-primary">按确认参数估算条件金额</summary>
    <form className="space-y-3 pb-3" onSubmit={run}>
      <p className="text-sm text-muted-foreground">
        {template === 'lease_exit' ? '假设退租赔付义务已触发，比较三种押金处理方式。'
          : '假设回购义务已触发，比较单利与按年复利。'} 请填写已确认参数，金额以元为单位。
      </p>
      <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-2">
        {[...fields[template], ['extra_fee', '其他费用（没有则填 0）']].map(([key, label]) => (
          <label key={key} className="space-y-1 text-sm">
            <span>{label}</span>
            <input className={fieldClass} type="number" min={0} step={key === 'years' ? 1 : 'any'} required
              value={String(parameters[key] ?? '')} onChange={(e) => update(key, e.target.value)} />
          </label>
        ))}
        <label className="space-y-1 text-sm">
          <span>责任上限</span>
          <select className={fieldClass} required value={String(parameters.cap_mode ?? '')}
            onChange={(e) => update('cap_mode', e.target.value)}>
            <option value="">请选择</option>
            <option value="none">确认无上限</option><option value="fixed">有金额上限</option>
          </select>
        </label>
        {parameters.cap_mode === 'fixed' && <label className="space-y-1 text-sm">
          <span>上限金额</span>
          <input className={fieldClass} type="number" min={0} step="any" required
            value={String(parameters.cap ?? '')} onChange={(e) => update('cap', e.target.value)} />
        </label>}
        {template === 'lease_exit' && <label className="flex min-h-11 items-center gap-2 text-sm sm:col-span-2">
          <input type="checkbox" required checked={confirm} onChange={(e) => { setConfirm(e.target.checked); setRows([]) }} />
          已确认退租时间、通知和豁免条件适用
        </label>}
      </fieldset>
      <Button className="min-h-11" variant="outline" type="submit" disabled={busy}>{busy ? '计算中…' : '计算条件金额'}</Button>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <ul aria-live="polite" className="space-y-2 text-sm">{rows.map((row) => <li key={row.label} className="rounded-md bg-muted p-3">
        <strong>{row.label}：{row.amount === null ? '待确认' : money.format(row.amount)}</strong>
        <p className="mt-1 break-words text-muted-foreground">{row.formula || row.missing.join('、')}</p>
      </li>)}</ul>
    </form>
  </details>
}
