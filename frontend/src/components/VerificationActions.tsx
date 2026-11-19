import { useState } from 'react'
import { Button } from './ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'
import { reviewVerification, updateFacts, workflowError, type Verification } from '@/lib/workflows'

const fields = [['used_sessions', '已上课节数'], ['total_paid', '实付金额（元）'],
  ['unit_price', '每节原价（元）'], ['request_day', '申请距合同约定起点的天数']] as const
const labels: Record<string, string> = { consistent: '一致', conflict: '矛盾', unclear: '证据不足' }

export function VerificationActions({ task, onUpdate, onResolve }: {
  task: Verification; onUpdate: (v: Verification) => void; onResolve: (id: string) => void
}) {
  const [facts, setFacts] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(task.confirmed_facts ?? {}).map(([k, v]) => [k, String(v)])))
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  if (!task.task_id) return null
  async function run(action: 'facts' | 'review') {
    setBusy(action); setError('')
    try {
      const input = Object.fromEntries(Object.entries(facts).filter(([, v]) => v !== '').map(([k, v]) =>
        [k, k === 'request_phase' ? v : Number(v)]))
      onUpdate(await (action === 'facts' ? updateFacts(task, input) : reviewVerification(task)))
    } catch (e) { setError(workflowError(e)) } finally { setBusy('') }
  }
  return <Card>
    <CardHeader><CardTitle>补充事实与模型复核</CardTitle></CardHeader>
    <CardContent className="space-y-4">
      <p className="text-sm text-muted-foreground">核验版本 {task.task_revision}。用户补充与合同原文分别保存；补充后重新计算，并使旧复核意见失效。</p>
      <form onSubmit={(e) => { e.preventDefault(); void run('facts') }} className="space-y-3">
        <fieldset disabled={!!busy} className="grid gap-3 sm:grid-cols-2">
          {fields.map(([key, label]) => <label key={key} className="space-y-1 text-sm">{label}
            <input type="number" min="0" step={key === 'used_sessions' || key === 'request_day' ? '1' : '.01'}
              className="block w-full rounded border bg-background p-2" value={facts[key] ?? ''}
              onChange={(e) => setFacts({ ...facts, [key]: e.target.value })} />
          </label>)}
          <label className="text-sm">申请阶段<select className="mt-1 block w-full rounded border bg-background p-2"
            value={facts.request_phase ?? ''} onChange={(e) => setFacts({ ...facts, request_phase: e.target.value })}>
            <option value="">尚未确认</option><option>开课前</option><option>开课后</option>
          </select></label>
        </fieldset>
        <Button disabled={!!busy} type="submit">{busy === 'facts' ? '更新中…' : '确认事实并继续核验'}</Button>
      </form>
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
