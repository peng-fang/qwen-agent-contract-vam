import { useRef, useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { VamEvidenceInput } from '@/lib/api'
import {
  checklistError, fieldClass, runChecklist, type ChecklistItem, type ChecklistResult, type Priority,
} from '@/lib/checklist'
import { ChecklistEstimate } from './ChecklistEstimate'

const priorities: Record<Priority, [string, string]> = {
  must_confirm: ['签前必须确认', 'bg-red-50 text-red-800'],
  should_confirm: ['建议确认', 'bg-amber-50 text-amber-900'],
  reference: ['留作记录', 'bg-slate-100 text-slate-700'],
}
const example = '第三条：承租人交付押金5000元。承租人违约时，出租人可以扣除押金。\n第八条：承租人提前解除合同，应支付10000元违约金。\n第九条：租期届满前如未按期通知，合同自动续租。'
const panel = 'rounded-xl border border-border bg-background p-4 sm:p-6'

function ChecklistCard({ item, leaseContext }: { item: ChecklistItem; leaseContext: boolean }) {
  const [copyState, setCopyState] = useState('')
  const quotes = item.evidence.map((source) => source.quote).join('')
  const prompt = item.title + item.question + item.trigger + item.consequence + quotes
  const template = /回购/.test(quotes) ? 'repurchase'
    : (leaseContext || /退租|租期|租赁|承租|出租/.test(prompt)) && /提前|退租|违约金/.test(prompt)
      && /押金/.test(prompt) ? 'lease_exit' : null
  const [priority, colors] = item.priority ? priorities[item.priority] : ['暂未定级', 'bg-slate-100 text-slate-700']

  async function copy() {
    try {
      await navigator.clipboard.writeText(item.question)
      setCopyState('已复制')
    } catch { setCopyState('可选中文字手动复制') }
  }

  return <article className={panel + ' space-y-4'}>
    <div className="flex flex-wrap items-center gap-3">
      <span className={'rounded-full px-2.5 py-1 text-xs font-semibold ' + colors}>{priority}</span>
      <h3 className="min-w-0 break-words text-lg font-semibold">{item.title}</h3>
    </div>
    <dl className="space-y-2 break-words text-sm leading-6">
      <div><dt className="inline font-medium">什么时候会遇到：</dt><dd className="inline">{item.trigger}</dd></div>
      <div><dt className="inline font-medium">可能后果：</dt><dd className="inline">{item.consequence}</dd></div>
    </dl>
    <div className="rounded-lg bg-blue-50 p-3 text-blue-950">
      <p className="text-sm font-semibold">可以这样问</p>
      <p className="mt-1 break-words leading-6">{item.question}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" className="min-h-11" onClick={() => void copy()}>复制问题</Button>
        <span className="text-sm" role="status">{copyState}</span>
      </div>
    </div>
    <details className="rounded-lg border px-3">
      <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">查看原文（{item.evidence.length} 处）</summary>
      <div className="space-y-3 pb-3">{item.evidence.map((source) =>
        <blockquote key={source.id + source.quote} className="border-l-2 pl-3 text-sm">
          <div className="break-words font-medium">{source.filename}{source.page !== null ? ' · 第 ' + source.page + ' 页' : ''}</div>
          <p className="mt-1 whitespace-pre-wrap break-words text-slate-700">{source.quote}</p>
        </blockquote>)}</div>
    </details>
    {template && <ChecklistEstimate template={template} />}
  </article>
}

export function ChecklistPage({ evidence, onRemoveEvidence }: {
  evidence: VamEvidenceInput[]; onRemoveEvidence: (index: number) => void
}) {
  const [source, setSource] = useState<'file' | 'text' | 'evidence'>(() => evidence.length ? 'evidence' : 'file')
  const [file, setFile] = useState<File>()
  const [text, setText] = useState('')
  const [role, setRole] = useState('')
  const [result, setResult] = useState<ChecklistResult>()
  const [leaseContext, setLeaseContext] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const results = useRef<HTMLElement>(null)

  async function run(e: FormEvent) {
    e.preventDefault()
    setError('')
    if ((source === 'file' && !file) || (source === 'text' && !text.trim()) || (source === 'evidence' && !evidence.length)) {
      setError('请先提供合同材料。')
      return
    }
    if (source === 'file' && file && file.size > 10 * 1024 * 1024) {
      setError('合同文件最多 10 MB。')
      return
    }
    setLoading(true)
    setResult(undefined)
    try {
      const material = source === 'file' ? { file } : source === 'text' ? { text } : { evidence }
      setResult(await runChecklist(role, material))
      setLeaseContext(/承租|出租|租客|租赁|房东|退租/.test(role + (material.text ?? '') + (material.file?.name ?? '')))
      requestAnimationFrame(() => results.current?.focus())
    } catch (error) { setError(checklistError(error)) } finally { setLoading(false) }
  }

  return <div className="mx-auto max-w-4xl space-y-5">
    <header className="space-y-2">
      <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">签约前必问清单</h1>
      <p className="leading-7 text-muted-foreground">从合同里找出签字前最值得问清楚的事项，查看原文和可能后果，把问题直接发给对方。</p>
    </header>
    <form className={panel} onSubmit={run}>
      <fieldset disabled={loading} className="space-y-4">
        <legend className="mb-3 text-lg font-semibold">提供合同材料</legend>
        <div className="flex flex-wrap gap-2" aria-label="合同材料来源">
          {([['file', '上传合同'], ['text', '粘贴条款'], ...(evidence.length ? [['evidence', '核验原文']] : [])] as
            ['file' | 'text' | 'evidence', string][]).map(([key, label]) => (
            <Button key={key} type="button" className="min-h-11" variant={source === key ? 'default' : 'outline'}
              aria-pressed={source === key} onClick={() => setSource(key)}>{label}</Button>))}
        </div>
        {source === 'file' && <label className="block space-y-1 text-sm">
          <span className="font-medium">合同文件（PDF 或 UTF-8 TXT，最多 10 MB）</span>
          <input className={fieldClass} type="file" accept=".pdf,.txt" onChange={(e) => setFile(e.target.files?.[0])} />
          {file && <span className="block break-words text-slate-600">已选：{file.name}</span>}
        </label>}
        {source === 'text' && <label className="block space-y-1 text-sm">
          <span className="font-medium">合同条款</span>
          <Textarea rows={5} maxLength={24000} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="把需要确认的一段或几段条款粘贴到这里。" />
        </label>}
        {source === 'evidence' && <div className="space-y-2 text-sm">{evidence.length ? evidence.map((item, index) =>
          <div key={item.file_id + item.page + item.quote} className="flex items-start gap-3 rounded-lg border p-3">
            <div className="min-w-0 flex-1 break-words"><strong>{item.filename} · 第 {item.page} 页</strong><p className="whitespace-pre-wrap">{item.quote}</p></div>
            <Button type="button" variant="outline" className="min-h-11" aria-label={'移除原文 ' + (index + 1)} onClick={() => onRemoveEvidence(index)}>移除</Button>
          </div>) : <p>可返回合同核验定位并带入 PDF 原文。</p>}</div>}
        <label className="block max-w-md space-y-1 text-sm">
          <span className="font-medium">我的身份（可选）</span>
          <input className={fieldClass} maxLength={80} value={role} onChange={(e) => setRole(e.target.value)}
            placeholder="如：承租人、消费者、采购方、融资方" />
        </label>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" className="min-h-11">{loading ? '正在生成…' : '生成必问清单'}</Button>
          <Button type="button" variant="outline" className="min-h-11"
            onClick={() => { setSource('text'); setText(example); setRole('承租人'); setResult(undefined); setError('') }}>填入租赁示例</Button>
        </div>
      </fieldset>
      {loading && <p className="mt-3 text-sm text-muted-foreground" role="status">正在核对引文并判断确认顺序，较长材料可能需要一点时间。</p>}
      {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800" role="alert">{error}</p>}
    </form>
    {result && <section ref={results} tabIndex={-1} className="space-y-3">
      <div className="space-y-1">
        <h2 className="text-xl font-semibold">我该先问什么</h2>
        <p className="text-sm text-muted-foreground">分析范围：{result.scope} · {result.items.length} 条待确认事项
          {result.priority_model && ' · 优先级模型：' + result.priority_model}</p>
        {result.warning && <p role="status" className="text-sm text-amber-900">{result.warning}</p>}
      </div>
      {result.items.length
        ? result.items.map((item) => <ChecklistCard key={item.id} item={item} leaseContext={leaseContext} />)
        : <p className={panel}>这次没有找到能回指原文的待确认事项。可以补充相关条款后再试。</p>}
    </section>}
  </div>
}
