import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { VamEvidenceInput } from '@/lib/api'
import {
  checklistError, exportChecklistPdf, fieldClass, runChecklistStream, type ChecklistItem, type ChecklistProgress,
  type ChecklistResult, type Priority,
} from '@/lib/checklist'
import { ChecklistEstimate } from './ChecklistEstimate'
import { ChecklistEvidenceLocator } from './ChecklistEvidenceLocator'

const priorities: Record<Priority, [string, string]> = {
  must_confirm: ['签前必须确认', 'bg-red-50 text-red-800'],
  should_confirm: ['建议确认', 'bg-amber-50 text-amber-900'],
  reference: ['留作记录', 'bg-slate-100 text-slate-700'],
}
const example = '第三条：承租人交付押金5000元。承租人违约时，出租人可以扣除押金。\n第八条：承租人提前解除合同，应支付10000元违约金。\n第九条：租期届满前如未按期通知，合同自动续租。'
const panel = 'rounded-xl border border-border bg-background p-4 sm:p-6'
const stages: Array<[string, string]> = [
  ['parse', '读取材料'],
  ['generate', '生成问题'],
  ['priority', '判断优先级'],
  ['done', '完成'],
]

function ChecklistCard({ item, leaseContext, selected, onSelect }: {
  item: ChecklistItem
  leaseContext: boolean
  selected?: boolean
  onSelect?: (selected: boolean) => void
}) {
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
      {onSelect && (
        <input
          type="checkbox"
          className="h-4 w-4 accent-blue-600"
          checked={Boolean(selected)}
          onChange={(event) => onSelect(event.target.checked)}
          aria-label={`选择问题：${item.title}`}
        />
      )}
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

export function ChecklistPage({ evidence, onRemoveEvidence, sharedFiles = [], onFilesChange, onRemoveFile }: {
  evidence: VamEvidenceInput[]; onRemoveEvidence: (index: number) => void
  sharedFiles?: File[]; onFilesChange?: (files: File[]) => void; onRemoveFile?: (file: File) => void
}) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [text, setText] = useState('')
  const initializedFile = useRef(false)
  const [role, setRole] = useState('')
  const [result, setResult] = useState<ChecklistResult>()
  const [leaseContext, setLeaseContext] = useState(false)
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState<Record<string, ChecklistProgress>>({})
  const [partialItems, setPartialItems] = useState<ChecklistItem[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState('')
  const results = useRef<HTMLElement>(null)

  useEffect(() => {
    if (initializedFile.current || !sharedFiles.length) return
    const shared = sharedFiles.find((item) => /\.(pdf|txt)$/i.test(item.name))
    if (shared) {
      setSelectedFiles([shared])
      initializedFile.current = true
    }
  }, [sharedFiles])

  function toggleFile(file: File) {
    setSelectedFiles((current) => current.some((item) => item.name === file.name && item.lastModified === file.lastModified)
      ? current.filter((item) => !(item.name === file.name && item.lastModified === file.lastModified))
      : [...current, file])
  }

  const locatorFiles = selectedFiles.filter((file) =>
    !sharedFiles.some((item) => item.name === file.name && item.lastModified === file.lastModified))
    .concat(sharedFiles)

  useEffect(() => {
    if (!loading) return
    const started = Date.now()
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - started) / 1000))
    }, 1000)
    return () => {
      window.clearInterval(timer)
      setElapsed(0)
    }
  }, [loading])

  async function run(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (!selectedFiles.length && !text.trim() && !evidence.length) {
      setError('请至少提供一种材料：上传合同、粘贴条款或核验原文。')
      return
    }
    if (selectedFiles.some((item) => item.size > 10 * 1024 * 1024)) {
      setError('合同文件最多 10 MB。')
      return
    }
    setLoading(true)
    setResult(undefined)
    setProgress({})
    setPartialItems([])
    const material = {
      ...(selectedFiles.length ? { files: selectedFiles } : {}),
      ...(text.trim() ? { text } : {}),
      ...(evidence.length ? { evidence } : {}),
    }
    setLeaseContext(/承租|出租|租客|租赁|房东|退租/.test(role + text + selectedFiles.map((item) => item.name).join('')))
    try {
      const data = await runChecklistStream(
        role,
        material,
        (event) => setProgress((prev) => ({ ...prev, [event.stage]: event })),
        (items) => {
          setPartialItems(items)
          setProgress((prev) => ({
            ...prev,
            generate: { stage: 'generate', status: 'done', detail: '候选问题已生成。' },
            priority: { stage: 'priority', status: 'running', detail: '正在判断优先级。' },
          }))
        },
      )
      setProgress({
        parse: { stage: 'parse', status: 'done', detail: '' },
        generate: { stage: 'generate', status: 'done', detail: '' },
        priority: { stage: 'priority', status: 'done', detail: '' },
        done: { stage: 'done', status: 'done', detail: '' },
      })
      setResult(data)
      setSelectedIds(new Set(data.items.map((item) => item.id)))
      requestAnimationFrame(() => results.current?.focus())
    } catch (error) {
      setError(error instanceof Error ? error.message : checklistError(error))
    } finally {
      setLoading(false)
    }
  }

  async function exportSelected() {
    if (!result) return
    const items = result.items.filter((item) => selectedIds.has(item.id))
    if (!items.length) {
      setExportError('请至少选择一条要导出 PDF 的问题。')
      return
    }
    setExporting(true)
    setExportError('')
    try {
      const blob = await exportChecklistPdf(items, role, result.scope)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = '签约前必问清单.pdf'
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      setExportError(error instanceof Error ? error.message : '导出 PDF 失败')
    } finally {
      setExporting(false)
    }
  }

  return <div className="mx-auto max-w-[1700px] space-y-5">
    <header className="space-y-2">
      <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">签约前必问清单</h1>
      <p className="leading-7 text-muted-foreground">从合同里找出签字前最值得问清楚的事项，查看原文和可能后果，把问题直接发给对方。</p>
    </header>
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_680px] 2xl:grid-cols-[minmax(0,1fr)_820px]">
      <div className="min-w-0 space-y-5">
    <form className={panel} onSubmit={run}>
      <fieldset disabled={loading} className="space-y-4">
        <legend className="mb-3 text-lg font-semibold">提供合同材料</legend>
        <div className="space-y-2 text-sm">
          <div className="font-medium">工作区文件</div>
          {sharedFiles.length ? (
            <div className="space-y-2">
              {sharedFiles.map((item) => {
                const active = selectedFiles.some((file) => file.name === item.name && file.lastModified === item.lastModified)
                return (
                  <div key={item.name + item.lastModified} className="flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2">
                    <span className="min-w-0 flex-1 break-words">{item.name}</span>
                    <Button type="button" variant={active ? 'default' : 'outline'} size="sm" onClick={() => toggleFile(item)}>
                      {active ? '已使用' : '使用'}
                    </Button>
                    {onRemoveFile && (
                      <Button type="button" variant="outline" size="sm" onClick={() => {
                        onRemoveFile(item)
                        setSelectedFiles((current) => current.filter((file) =>
                          !(file.name === item.name && file.lastModified === item.lastModified)))
                      }}>移除</Button>
                    )}
                  </div>
                )
              })}
            </div>
          ) : <p className="text-muted-foreground">前两页上传的文件会显示在这里；也可以直接在下方新增。</p>}
        </div>
        <label className="block space-y-1 text-sm">
          <span className="font-medium">新增合同文件（PDF 或 UTF-8 TXT，最多 10 MB）</span>
          <input className={fieldClass} type="file" accept=".pdf,.txt" onChange={(e) => {
            const selected = e.target.files?.[0]
            if (!selected) return
            setSelectedFiles((current) => current.some((item) => item.name === selected.name)
              ? current
              : [...current, selected])
            onFilesChange?.([...sharedFiles.filter((item) => item.name !== selected.name), selected])
          }} />
          {selectedFiles.length > 0 && (
            <span className="block break-words text-slate-600">
              当前使用：{selectedFiles.map((item) => item.name).join('、')}
            </span>
          )}
        </label>
        <label className="block space-y-1 text-sm">
          <span className="font-medium">粘贴条款（可与文件、核验原文同时使用）</span>
          <Textarea rows={5} maxLength={24000} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="把需要确认的一段或几段条款粘贴到这里。" />
        </label>
        <div className="space-y-2 text-sm">
          <div className="font-medium">核验原文（可与文件、粘贴条款同时使用）</div>
          {evidence.length ? evidence.map((item, index) =>
            <div key={item.file_id + item.page + item.quote} className="flex items-start gap-3 rounded-lg border p-3">
              <div className="min-w-0 flex-1 break-words"><strong>{item.filename} · 第 {item.page} 页</strong><p className="whitespace-pre-wrap">{item.quote}</p></div>
              <Button type="button" variant="outline" className="min-h-11" aria-label={'移除原文 ' + (index + 1)} onClick={() => onRemoveEvidence(index)}>移除</Button>
            </div>) : <p className="text-muted-foreground">可以只用核验原文生成，不必再次上传合同。</p>}
        </div>
        <label className="block max-w-md space-y-1 text-sm">
          <span className="font-medium">我的身份（可选）</span>
          <input className={fieldClass} maxLength={80} value={role} onChange={(e) => setRole(e.target.value)}
            placeholder="如：承租人、消费者、采购方、融资方" />
        </label>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" className="min-h-11">{loading ? '正在生成…' : '生成必问清单'}</Button>
          <Button type="button" variant="outline" className="min-h-11"
            onClick={() => { setText(example); setRole('承租人'); setResult(undefined); setError('') }}>填入租赁示例</Button>
        </div>
      </fieldset>
      {loading && <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800" aria-live="polite">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span>正在生成签约前问题。</span>
          <span className="font-mono text-xs">已等待 {elapsed}s</span>
        </div>
        <div className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
          {stages.map(([key, label]) => {
            const event = progress[key]
            const marker = event?.status === 'done' ? '✓' : event?.status === 'warning' ? '!' : event?.status === 'running' ? '…' : '·'
            return <div key={key} className={event?.status === 'done' ? 'text-blue-800' : 'text-blue-600/70'}>
              <span className="mr-1 inline-block w-5 font-mono">{marker}</span>{label}
              {event?.detail && event.status !== 'done' ? ` · ${event.detail}` : ''}
            </div>
          })}
        </div>
      </div>}
      {loading && partialItems.length > 0 && <div className="mt-3 space-y-3">
        <p className="text-sm text-amber-900">已生成 {partialItems.length} 条候选问题，正在判断优先级；最终结果会自动更新。</p>
        {partialItems.map((item) => <ChecklistCard key={`partial-${item.id}`} item={item} leaseContext={leaseContext} />)}
      </div>}
      {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800" role="alert">{error}</p>}
    </form>
    {result && <section ref={results} tabIndex={-1} className="space-y-3">
      <div className="space-y-1">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">我该先问什么</h2>
            <p className="text-sm text-muted-foreground">分析范围：{result.scope} · {result.items.length} 条待确认事项
              {result.priority_model && ' · 优先级模型：' + result.priority_model}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                className="h-4 w-4 accent-blue-600"
                checked={result.items.length > 0 && result.items.every((item) => selectedIds.has(item.id))}
                onChange={(event) => setSelectedIds(event.target.checked
                  ? new Set(result.items.map((item) => item.id))
                  : new Set())}
              />
              全选
            </label>
            <Button type="button" variant="outline" disabled={exporting || selectedIds.size === 0} onClick={() => void exportSelected()}>
              {exporting ? '正在生成 PDF…' : `导出所选 PDF（${selectedIds.size}）`}
            </Button>
          </div>
        </div>
        {result.warning && <p role="status" className="text-sm text-amber-900">{result.warning}</p>}
        {exportError && <p role="alert" className="text-sm text-red-700">{exportError}</p>}
      </div>
      {result.items.length
        ? result.items.map((item) => (
          <ChecklistCard
            key={item.id}
            item={item}
            leaseContext={leaseContext}
            selected={selectedIds.has(item.id)}
            onSelect={(checked) => setSelectedIds((current) => {
              const next = new Set(current)
              if (checked) next.add(item.id)
              else next.delete(item.id)
              return next
            })}
          />
        ))
        : <p className={panel}>这次没有找到能回指原文的待确认事项。可以补充相关条款后再试。</p>}
    </section>}
      </div>
      <ChecklistEvidenceLocator files={locatorFiles} />
    </div>
  </div>
}
