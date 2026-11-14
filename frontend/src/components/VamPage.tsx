import { useRef, useState, type FormEvent } from 'react'
import axios from 'axios'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  compareVam, deepenVam, exportVam, runVam,
  type VamAction, type VamEvidenceInput, type VamResult, type VamStudy, type VamTrigger,
} from '@/lib/api'
import { ActionFields, WeightInputs } from './VamInputs'
import { VamResults } from './VamResults'
import { defaultWeights, examples, fieldClass, nodePath, objectives, roles, templates } from '@/lib/vam'

const emptyStudy: VamStudy = {
  role: null, objective: null, template: 'qualitative', actions: [],
  experimental_scoring: false, weights: defaultWeights,
}
const headingPanel = 'space-y-4 rounded-xl border border-border bg-background p-4 sm:p-6'

function message(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail: unknown = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((item) => String(item.msg ?? '输入有误')).join('。')
    }
  }
  return error instanceof Error ? error.message : '请求失败，请重试。'
}

function selectedFor(result: VamResult, preferred = ''): string {
  return nodePath(result.tree.branches, preferred).length
    ? preferred
    : result.comparison.scenarios[0]?.leaf_id ?? ''
}

function validateActions(actions: VamAction[]) {
  const labels = actions.map((action) => action.label.trim())
  if (labels.includes('') || new Set(labels).size !== labels.length) {
    throw new Error('每个方案需要不同的名称。')
  }
}

export function VamPage({ evidence, onRemoveEvidence }: {
  evidence: VamEvidenceInput[]
  onRemoveEvidence: (index: number) => void
}) {
  const [query, setQuery] = useState('')
  const [study, setStudy] = useState<VamStudy>(emptyStudy)
  const [result, setResult] = useState<VamResult | null>(null)
  const [history, setHistory] = useState<{ result: VamResult; selectedId: string }[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [actions, setActions] = useState<VamAction[]>([])
  const [weights, setWeights] = useState(defaultWeights)
  const [loading, setLoading] = useState('')
  const [error, setError] = useState('')
  const resultsRef = useRef<HTMLDivElement>(null)

  function show(next: VamResult, preferred = '') {
    setResult(next)
    setSelectedId(selectedFor(next, preferred))
    setActions(next.study.actions)
    setWeights(next.study.weights)
  }

  function applyExample(example: typeof examples[number]) {
    setQuery(example.query)
    setStudy({ ...emptyStudy, role: example.role, template: example.template, objective: 'cash', actions: example.actions })
    setError('')
  }

  async function perform(label: string, operation: () => Promise<void>) {
    setError('')
    setLoading(label)
    try {
      await operation()
    } catch (error) {
      setError(message(error))
    } finally {
      setLoading('')
    }
  }

  async function run(e: FormEvent) {
    e.preventDefault()
    await perform('正在生成合同情景…', async () => {
      if (!query.trim() && !evidence.length) throw new Error('填写条款、背景，或从核验页带入原文。')
      validateActions(study.actions)
      if (study.experimental_scoring && (!study.role || !study.objective)) {
        throw new Error('开启实验评分前，请选择身份和关注目标。')
      }
      const next = await runVam(query, study, evidence)
      setHistory([])
      show(next)
      requestAnimationFrame(() => resultsRef.current?.focus())
    })
  }

  async function compare(triggerOverride?: { id: string; value: VamTrigger }) {
    if (!result) return
    await perform('正在重新比较…', async () => {
      if (!triggerOverride) validateActions(actions)
      const next = await compareVam(result, triggerOverride ? result.study.actions : actions,
        triggerOverride ? result.study.weights : weights,
        triggerOverride ? { [triggerOverride.id]: triggerOverride.value } : {})
      setHistory((items) => [...items.slice(-10), { result, selectedId }])
      if (triggerOverride) {
        setResult(next)
        setSelectedId(triggerOverride.id)
      } else {
        show(next, selectedId)
      }
    })
  }

  async function deepen() {
    if (!result || !selectedId) return
    await perform('正在展开所选情景…', async () => {
      const next = await deepenVam(result, selectedId)
      setHistory((items) => [...items.slice(-10), { result, selectedId }])
      const child = next.comparison.scenarios.find((scenario) => scenario.path.includes(selectedId))
      show(next, child?.leaf_id ?? selectedId)
    })
  }

  function back() {
    const previous = history.at(-1)
    if (!previous) return
    setError('')
    setHistory(history.slice(0, -1))
    show(previous.result, previous.selectedId)
  }

  async function download() {
    if (!result) return
    await perform('正在生成报告…', async () => {
      const report = await exportVam(result)
      const href = URL.createObjectURL(new Blob([report], { type: 'text/markdown;charset=utf-8' }))
      const link = document.createElement('a')
      link.href = href
      link.download = '合同情景分析报告.md'
      link.click()
      setTimeout(() => URL.revokeObjectURL(href), 1000)
    })
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <header>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">合同情景分析与方案比较</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
          看清哪些条件会触发合同义务，比较不同方案的金额、付款时间和待确认事项，并回查合同原文。
        </p>
      </header>

      <form className={headingPanel} onSubmit={run}>
        <fieldset className="space-y-4" disabled={Boolean(loading)}>
          <legend className="mb-3 text-lg font-semibold">条款与比较目标</legend>
          <div className="flex flex-wrap gap-2" aria-label="填入示例">
            {examples.map((example) => (
              <Button key={example.title} type="button" variant="outline" className="min-h-11" onClick={() => applyExample(example)}>
                {example.title}
              </Button>
            ))}
          </div>
          {!query && !result && (
            <p className="rounded-md bg-muted p-3 text-sm leading-6 text-muted-foreground">
              例如，业绩未达标时，回购原条款的条件金额为 1240 万元。若协商后的回购上限为 1100 万元，该情景下少承担 140 万元。
            </p>
          )}
          <label className="block space-y-1 text-sm font-medium">
            <span>合同条款或补充背景</span>
            <Textarea rows={4} maxLength={12000} value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="粘贴条款，或补充已从核验页带入的条款背景。" />
          </label>
          {evidence.length > 0 && (
            <div className="space-y-2 rounded-lg border p-3 text-sm">
              <h3 className="font-semibold">从合同核验带入的原文</h3>
              {evidence.map((item, index) => (
                <div key={item.file_id + item.page + item.quote} className="flex items-start justify-between gap-3 border-t pt-2">
                  <div className="min-w-0 break-words">
                    <p className="font-medium">{item.filename} · 第 {item.page} 页</p>
                    <p className="whitespace-pre-wrap text-muted-foreground">{item.quote}</p>
                  </div>
                  <Button type="button" variant="ghost" aria-label={'移除原文 ' + (index + 1)} className="min-h-11"
                    onClick={() => onRemoveEvidence(index)}>移除</Button>
                </div>
              ))}
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="space-y-1 text-sm">
              <span>我的身份</span>
              <select className={fieldClass} value={study.role ?? ''}
                onChange={(e) => setStudy({ ...study, role: (e.target.value || null) as VamStudy['role'] })}>
                <option value="">请选择</option>
                {Object.entries(roles).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span>关注目标</span>
              <select className={fieldClass} value={study.objective ?? ''}
                onChange={(e) => setStudy({ ...study, objective: (e.target.value || null) as VamStudy['objective'] })}>
                <option value="">请选择</option>
                {Object.entries(objectives).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span>分析内容</span>
              <select className={fieldClass} value={study.template}
                onChange={(e) => setStudy({ ...study, template: e.target.value as VamStudy['template'],
                  actions: study.actions.map((action) => ({ ...action, parameters: {} })) })}>
                {Object.entries(templates).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          </div>
          <details open={study.actions.length > 0 || undefined} className="space-y-3 rounded-lg border p-3">
            <summary className="cursor-pointer text-sm font-medium">填写方案与计算参数</summary>
            {study.template !== 'qualitative' && <p className="text-sm text-muted-foreground">
              金额比较适用于触发条件相同的方案。若修改的是触发门槛或适用范围，请改用条款比较，或重新填写背景后推演。
            </p>}
            <ActionFields template={study.template} actions={study.actions} onChange={(next) => setStudy({ ...study, actions: next })} />
          </details>
          <details className="space-y-3 rounded-lg border p-3">
            <summary className="cursor-pointer text-sm font-medium">实验评分设置{study.experimental_scoring && '（已开启）'}</summary>
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input type="checkbox" checked={study.experimental_scoring}
                onChange={(e) => setStudy({ ...study, experimental_scoring: e.target.checked })} />
              为外部情景生成实验评分
            </label>
            <p className="text-sm text-muted-foreground">用于观察不利程度、应对条件和条件负担。方案依据条件后果进行比较。</p>
            {study.experimental_scoring &&
              <WeightInputs value={study.weights} onChange={(next) => setStudy({ ...study, weights: next })} />}
          </details>
          <Button type="submit" className="min-h-11">{result ? '按当前输入重新推演' : '开始情景分析'}</Button>
        </fieldset>
      </form>

      <div aria-live="polite">
        {loading && <p className="rounded-md bg-blue-50 p-3 text-sm font-medium text-blue-900">{loading}</p>}
      </div>
      {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900">{error}</p>}

      {result && (
        <div ref={resultsRef} tabIndex={-1} className="space-y-4">
          <VamResults result={result} selectedId={selectedId} setSelectedId={setSelectedId} busy={Boolean(loading)}
            onDeepen={() => void deepen()} canBack={history.length > 0} onBack={back} onExport={() => void download()}
            onTrigger={(id, value) => void compare({ id, value })} />
          <details className={headingPanel}>
            <summary className="cursor-pointer text-lg font-semibold">调整方案与参数</summary>
            <p className="text-sm text-muted-foreground">修改回购利率、责任上限或其他参数，直接比较当前情景下的新结果。修改条款文字后，可重新推演以更新模型说明。</p>
            <form onSubmit={(e) => { e.preventDefault(); void compare() }}>
              <fieldset disabled={Boolean(loading)} className="space-y-4">
                <ActionFields template={result.study.template} actions={actions} onChange={setActions} />
                {result.study.experimental_scoring && <WeightInputs value={weights} onChange={setWeights} />}
                <Button type="submit" className="min-h-11">按新参数重新比较</Button>
              </fieldset>
            </form>
          </details>
        </div>
      )}
    </div>
  )
}
