import { useState } from 'react'
import { Button } from './ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'
import { reviewVerification, updateFacts, workflowError, type RefundFact, type Verification } from '@/lib/workflows'

const fields = [['used_sessions', '已上课节数'], ['total_paid', '实付金额（元）'],
  ['unit_price', '每节原价（元）'], ['request_day', '申请距合同约定起点的天数']] as const
const labels: Record<string, string> = { consistent: '一致', conflict: '矛盾', unclear: '证据不足' }
const inputClass = 'block w-full rounded border bg-background p-2'

function FactInput({ field, value, onChange, required }: {
  field: RefundFact; value: string; onChange: (value: string) => void; required?: boolean
}) {
  if (field === 'request_phase') {
    return <select className={inputClass} required={required} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">尚未确认</option><option>开课前</option><option>开课后</option>
    </select>
  }
  return <input type="number" min="0" step={field === 'used_sessions' || field === 'request_day' ? '1' : '.01'}
    className={inputClass} required={required} value={value} onChange={(e) => onChange(e.target.value)} />
}

export function VerificationActions({ task, onUpdate, onResolve }: {
  task: Verification; onUpdate: (v: Verification) => void; onResolve: (id: string) => void
}) {
  const [facts, setFacts] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(task.confirmed_facts ?? {}).map(([k, v]) => [k, String(v)])))
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const next = task.refund_question
  const nextEvidenceId = next?.evidence_id
  if (!task.task_id) return null
  async function run(action: 'facts' | 'review', field?: RefundFact) {
    setBusy(action); setError('')
    try {
      const input = Object.fromEntries(Object.entries(facts).filter(([k, v]) => v !== '' && (!field || k === field)).map(([k, v]) =>
        [k, k === 'request_phase' ? v : Number(v)]))
      onUpdate(await (action === 'facts' ? updateFacts(task, input) : reviewVerification(task)))
    } catch (e) { setError(workflowError(e)) } finally { setBusy('') }
  }
  return <Card>
    <CardHeader><CardTitle>补充事实与模型复核</CardTitle></CardHeader>
    <CardContent className="space-y-4">
      <p className="text-sm text-muted-foreground">核验版本 {task.task_revision}。用户补充与合同原文分别保存；补充后重新计算，并使旧复核意见失效。</p>
      {next && <form onSubmit={(e) => { e.preventDefault(); void run('facts', next.field) }}
        className="space-y-3 rounded-md border bg-muted/40 p-3" aria-label="优先确认的退款问题">
        <fieldset disabled={!!busy}>
          <label className="block space-y-2 text-sm font-medium">
            <span>{next.question}</span>
            <FactInput field={next.field} required value={facts[next.field] ?? ''}
              onChange={(value) => setFacts({ ...facts, [next.field]: value })} />
          </label>
        </fieldset>
        {next.condition && <p className="text-xs text-muted-foreground">
          这会影响是否满足「{next.condition}」。
          {nextEvidenceId && <button type="button" className="ml-2 text-blue-600 underline"
            onClick={() => onResolve(nextEvidenceId)}>查看依据</button>}
        </p>}
        <Button type="submit" disabled={!!busy}>{busy === 'facts' ? '更新中…' : '确认并重新核验'}</Button>
      </form>}
      <details open={next ? undefined : true}>
        <summary className="mb-2 cursor-pointer text-sm font-medium">查看或更正全部事实</summary>
        <form onSubmit={(e) => { e.preventDefault(); void run('facts') }} className="space-y-3">
        <fieldset disabled={!!busy} className="grid gap-3 sm:grid-cols-2">
          {fields.map(([key, label]) => <label key={key} className="space-y-1 text-sm">{label}
            <FactInput field={key} value={facts[key] ?? ''}
              onChange={(value) => setFacts({ ...facts, [key]: value })} />
          </label>)}
          <label className="text-sm">申请阶段<FactInput field="request_phase" value={facts.request_phase ?? ''}
            onChange={(value) => setFacts({ ...facts, request_phase: value })} /></label>
        </fieldset>
        <Button disabled={!!busy} type="submit">{busy === 'facts' ? '更新中…' : '确认事实并继续核验'}</Button>
        </form>
      </details>
      <div className="border-t pt-3">
        <p className="mb-2 text-sm text-muted-foreground">模型重新阅读双方原文，复核时段、主体和例外。下方保留规则结论供比较。</p>
        <Button disabled={!!busy} variant="outline" onClick={() => void run('review')}>{busy === 'review' ? '模型复核中…' : '模型复核当前结论'}</Button>
      </div>
      {error && <p role="alert" className="text-sm text-red-700">{error}。原核验结果仍保留；如记录冲突，请恢复最近一次核验。</p>}
      {task.semantic_review && <div className="space-y-3" aria-live="polite">
        <p className="text-sm">当前展示复核后的结论及风险统计 · {task.semantic_review.model.model}</p>
        {task.semantic_review.items.map((item) => <div key={item.clause_type} className="rounded border p-3 text-sm">
          <strong>{labels[item.original_verdict] ?? item.original_verdict} → {labels[item.verdict]}</strong>
          <p className="my-2">{item.reason}</p>
          {item.evidence.map((entry) => <button key={entry.evidence_id} className="mr-3 underline" onClick={() => onResolve(entry.evidence_id)}>第{entry.page}页：{entry.quote.slice(0, 40)}</button>)}
        </div>)}
        <p className="text-xs text-muted-foreground">{task.semantic_review.note}</p>
      </div>}
    </CardContent>
  </Card>
}
