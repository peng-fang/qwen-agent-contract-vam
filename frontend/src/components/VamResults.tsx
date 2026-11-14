import { useMemo } from 'react'
import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Button } from '@/components/ui/button'
import type { VamConsequence, VamResult, VamScenarioComparison, VamTreeNode, VamTrigger } from '@/lib/api'
import { fieldClass, nodePath, objectives, roles, scoreFields, scoreKeys, templates, triggers } from '@/lib/vam'

const panel = 'space-y-4 rounded-xl border border-border bg-background p-4 sm:p-5'
const currency = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY',
  minimumFractionDigits: 0, maximumFractionDigits: 2 })
const scoreStatuses = { valid: '评分可用', missing: '信息不足', invalid: '分值无效', error: '评分失败', disabled: '未开启评分' }

function buildGraph(branches: VamTreeNode[], selectedId: string) {
  const nodes: Node[] = []
  const edges: Edge[] = []
  const width = 202
  const gap = 28
  const root = '__scenario_root__'

  function subtreeWidth(node: VamTreeNode): number {
    return node.children.length
      ? node.children.reduce((sum, child) => sum + subtreeWidth(child), 0) + gap * (node.children.length - 1)
      : width
  }

  function place(node: VamTreeNode, depth: number, left: number, parent: string) {
    const label = node.branch.length > 44 ? node.branch.slice(0, 43) + '…' : node.branch
    const selected = node.id === selectedId
    nodes.push({
      id: node.id,
      position: { x: left + (subtreeWidth(node) - width) / 2, y: depth * 108 },
      ariaLabel: node.branch,
      data: { label },
      style: {
        width, padding: 10, borderRadius: 8, fontSize: 13, whiteSpace: 'normal', overflowWrap: 'anywhere',
        color: 'hsl(var(--foreground))', background: selected ? '#eff6ff' : 'hsl(var(--background))',
        border: selected ? '2px solid hsl(var(--primary))' : '1px solid #94a3b8', cursor: 'pointer',
      },
    })
    edges.push({ id: parent + '/' + node.id, source: parent, target: node.id,
      type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed } })
    let childLeft = left
    for (const child of node.children) {
      place(child, depth + 1, childLeft, node.id)
      childLeft += subtreeWidth(child) + gap
    }
  }

  let left = 0
  for (const branch of branches) {
    place(branch, 1, left, root)
    left += subtreeWidth(branch) + gap
  }
  nodes.push({
    id: root, position: { x: (left - gap - width) / 2, y: 0 }, data: { label: '合同触发条件' },
    selectable: false, focusable: false,
    style: { width, background: '#e2e8f0', border: '1px solid #94a3b8', borderRadius: 8 },
  })
  return { nodes, edges }
}

function Consequence({ cell, direction, baseline, usesAmounts }: {
  cell: VamConsequence
  direction: VamResult['comparison']['direction']
  baseline?: number | null
  usesAmounts: boolean
}) {
  return (
    <div className="space-y-1.5">
      {usesAmounts && <div className="text-lg font-semibold tabular-nums">
        {cell.amount === null ? '待确认' : currency.format(cell.amount)}
      </div>}
      {cell.amount !== null && (
        <div className="text-xs text-muted-foreground">
          {direction === 'pay' ? '该项承担金额' : direction === 'receive' ? '合同约定应收金额' : '该项条件金额'}
          {baseline != null && cell.amount !== baseline && (
            <span> · 较首个方案{cell.amount < baseline ? '减少 ' : '增加 '}{currency.format(Math.abs(cell.amount - baseline))}</span>
          )}
        </div>
      )}
      {cell.payment_days != null && <div>触发后 {cell.payment_days} 天付款</div>}
      {cell.cap != null && <div>责任上限 {currency.format(cell.cap)}</div>}
      {usesAmounts && cell.missing.length > 0 && <div className="text-amber-900">待确认：{cell.missing.join('、')}</div>}
      {cell.effect && <div className="break-words text-muted-foreground">模型推演：{cell.effect}</div>}
      {!usesAmounts && !cell.effect && <div className="text-muted-foreground">该方案在此情景下的具体后果待确认。</div>}
      {cell.formula && (
        <details className="break-all text-muted-foreground">
          <summary className="cursor-pointer py-1 text-primary">查看计算式</summary>
          {cell.formula}
        </details>
      )}
    </div>
  )
}

function Comparison({ result, selectedId, onSelect, onTrigger, busy }: {
  result: VamResult
  selectedId: string
  onSelect: (id: string) => void
  onTrigger: (id: string, trigger: VamTrigger) => void
  busy: boolean
}) {
  const { actions, role, objective, template } = result.study
  const { scenarios, direction, max_amounts: peaks } = result.comparison
  if (!actions.length) {
    return <section className={panel}><h2 className="text-lg font-semibold">方案比较</h2>
      <p className="text-sm text-muted-foreground">下方可查看合同情景。在“调整方案与参数”中填写方案后，可比较同一情景下的后果。</p>
    </section>
  }
  const active = scenarios.find((row) => row.leaf_id === selectedId) ?? scenarios[0]
  return (
    <section className={panel}>
      <div>
        <h2 className="text-lg font-semibold">同一情景下的方案比较</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {role ? roles[role] : '身份待确认'} · {objective ? objectives[objective] : '目标待确认'} · {templates[template]}
        </p>
      </div>
      <label className="block max-w-xl space-y-1 text-sm font-medium">
        <span>选择要比较的情景</span>
        <select className={fieldClass} value={active.leaf_id} onChange={(e) => onSelect(e.target.value)}>
          {scenarios.map((row) => (
            <option key={row.leaf_id} value={row.leaf_id}>{row.path.join(' → ')} · {row.branch}</option>
          ))}
        </select>
      </label>
      {template !== 'qualitative' && <TriggerControl scenario={active} result={result} busy={busy} onChange={onTrigger} />}
      {result.tree.trigger_excerpt && (
        <blockquote className="break-words border-l-2 pl-3 text-sm text-muted-foreground">
          <span className="font-medium">供核对的条件片段 · {result.tree.trigger_excerpt.evidence_id ?? '用户背景'}</span>
          <p>{result.tree.trigger_excerpt.quote}</p>
        </blockquote>
      )}
      <div className={'grid gap-3 md:grid-cols-2 ' + (actions.length === 3 ? 'xl:grid-cols-3' : '')}>
        {actions.map((action, index) => {
          const cell = active.cells.find((entry) => entry.action_id === action.id)
          if (!cell) return null
          const preferred = active.preferred_action_ids.includes(action.id)
          return (
            <article key={action.id} className={'min-w-0 space-y-2 rounded-lg border p-4 text-sm ' +
              (preferred ? 'border-blue-300 bg-blue-50/50' : 'bg-muted/30')}>
              <h3 className="break-words font-semibold">{action.label}</h3>
              {preferred && <p className="text-xs font-medium text-blue-800">
                {active.preferred_action_ids.length > 1 ? '按此目标并列' : '在此情景下符合当前目标'}
              </p>}
              {action.terms && <p className="whitespace-pre-wrap break-words text-muted-foreground">{action.terms}</p>}
              <Consequence cell={cell} direction={direction} usesAmounts={template !== 'qualitative'}
                baseline={index > 0 ? active.cells[0]?.amount : null} />
              {peaks[action.id] != null && (
                <p className="border-t pt-2 text-xs text-muted-foreground">已列情景中该项最高金额 {currency.format(peaks[action.id]!)}</p>
              )}
            </article>
          )
        })}
      </div>
      <p className="text-sm text-muted-foreground">{active.reason} {template !== 'qualitative' && '金额按表单参数和所选触发前提计算。'}</p>
    </section>
  )
}

function TriggerControl({ scenario, result, busy, onChange }: {
  scenario: VamScenarioComparison
  result: VamResult
  busy: boolean
  onChange: (id: string, trigger: VamTrigger) => void
}) {
  const path = nodePath(result.tree.branches, scenario.leaf_id)
  const original = path.at(-1)?.trigger ?? 'unknown'
  return (
    <label className="block max-w-xl space-y-1 text-sm">
      <span>计算采用的触发前提</span>
      <select className={fieldClass} disabled={busy} value={scenario.trigger}
        onChange={(e) => onChange(scenario.leaf_id, e.target.value as VamTrigger)}>
        {Object.entries(triggers).filter(([value]) => original === 'unknown' || value === 'unknown' || value === original)
          .map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select>
    </label>
  )
}

function Notes({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null
  return <div className="space-y-1"><h3 className="text-sm font-semibold">{title}</h3>
    <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
      {items.map((item, index) => <li className="break-words" key={index}>{item}</li>)}
    </ul>
  </div>
}

export function VamResults({ result, selectedId, setSelectedId, busy, onDeepen, onBack, canBack, onExport, onTrigger }: {
  result: VamResult
  selectedId: string
  setSelectedId: (id: string) => void
  busy: boolean
  onDeepen: () => void
  onBack: () => void
  canBack: boolean
  onExport: () => void
  onTrigger: (id: string, trigger: VamTrigger) => void
}) {
  const graph = useMemo(() => buildGraph(result.tree.branches, selectedId), [result.tree.branches, selectedId])
  const path = nodePath(result.tree.branches, selectedId)
  const node = path.at(-1)
  const evaluation = node?.evaluation
  const allNodes: VamTreeNode[] = []
  function collect(branches: VamTreeNode[]) {
    for (const branch of branches) {
      allNodes.push(branch)
      collect(branch.children)
    }
  }
  collect(result.tree.branches)
  const references = new Set(path.flatMap((item) => item.evidence_ids))
  const evidence = result.study.evidence.filter((item) => references.has(item.id))
  const canExpand = node && !node.children.length && path.length < 3 && result.comparison.scenarios.length < 10
  const incomplete = allNodes.filter((item) => item.evaluation && !['disabled', 'valid'].includes(item.evaluation.status)).length
  return (
    <div className="space-y-4" aria-busy={busy}>
      <div className="flex flex-wrap justify-between gap-2">
        <h2 className="min-w-0 break-words text-xl font-semibold">{result.scenario}</h2>
        <div className="flex flex-wrap gap-2">
          {canBack && <Button disabled={busy} variant="outline" className="min-h-11" onClick={onBack}>回溯一步</Button>}
          <Button disabled={busy} variant="outline" className="min-h-11" onClick={onExport}>导出 Markdown</Button>
        </div>
      </div>
      <Comparison result={result} selectedId={selectedId} onSelect={setSelectedId} onTrigger={onTrigger} busy={busy} />
      <section className={panel}>
        <h2 className="text-lg font-semibold">假设、待确认项与合同原文</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <Notes title="全局假设" items={result.assumptions} />
          <Notes title="待确认" items={result.uncertainties} />
        </div>
        <Notes title="情景覆盖说明" items={result.warnings} />
        {result.study.evidence.length ? (
          <details className="rounded-lg border p-3 text-sm">
            <summary className="cursor-pointer font-medium">查看所选合同原文（{result.study.evidence.length} 处）</summary>
            <div className="mt-2 space-y-2">{result.study.evidence.map((item) => (
              <blockquote key={item.id} className="break-words border-l-2 pl-3">
                <div className="font-medium">{item.id} · {item.filename} · 第 {item.page} 页</div>
                <p className="whitespace-pre-wrap text-muted-foreground">{item.quote}</p>
              </blockquote>
            ))}</div>
          </details>
        ) : <p className="text-sm text-muted-foreground">原文未关联。本次情景基于填写的背景。</p>}
      </section>
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <section className={panel}>
          <h2 className="text-lg font-semibold">情景树</h2>
          <div className="h-[320px] overflow-hidden rounded-lg border bg-slate-50 sm:h-[420px]">
            <ReactFlow key={result.run_id} nodes={graph.nodes} edges={graph.edges} fitView
              fitViewOptions={{ padding: 0.15 }} minZoom={0.15} nodesDraggable={false} nodesConnectable={false}
              onNodeClick={(_, item) => item.id !== '__scenario_root__' && setSelectedId(item.id)}
              zoomOnScroll={false} panOnScroll={false} proOptions={{ hideAttribution: true }}>
              <Background />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
        </section>
        <section className={panel}>
          <label className="block space-y-1 text-sm font-medium">
            <span>选择要进一步分析的情景</span>
            <select className={fieldClass} value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
              {allNodes.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.branch}</option>)}
            </select>
          </label>
          {node && (
            <div className="space-y-3">
              <h2 className="break-words text-lg font-semibold">{node.branch}</h2>
              <Notes title="完整路径与触发条件" items={path.map((item) => item.branch + '：' + (item.premise || '待确认'))} />
              <Notes title="可能后果" items={node.events} />
              <Notes title="不利因素" items={node.risks} />
              <Notes title="有利因素" items={node.upsides} />
              <Notes title="关键变量" items={node.key_variables} />
              {evidence.length > 0 ? (
                <div className="space-y-2 text-sm">
                  <h3 className="font-semibold">路径关联原文</h3>
                  {evidence.map((item) => (
                    <details key={item.id} className="rounded-md border p-2">
                      <summary className="cursor-pointer break-words">{item.id} · {item.filename} · 第 {item.page} 页</summary>
                      <p className="mt-1 whitespace-pre-wrap break-words text-muted-foreground">{item.quote}</p>
                    </details>
                  ))}
                </div>
              ) : <p className="text-sm text-muted-foreground">此路径没有关联到已提供的原文段落。</p>}
              {canExpand && <Button className="min-h-11" variant="outline" disabled={busy} onClick={onDeepen}>继续推演此情景</Button>}
            </div>
          )}
          {evaluation && evaluation.status !== 'disabled' && (
            <details className="rounded-md border p-3 text-sm">
              <summary className="cursor-pointer font-semibold">实验评分 · {scoreStatuses[evaluation.status]}</summary>
              <div className="mt-2 space-y-2 text-muted-foreground">
                {evaluation.scorer_model && <p>评分模型：{evaluation.scorer_model}</p>}
                <p>从{result.study.role ? roles[result.study.role] : '当前用户'}的立场评价此情景。此分用于观察情景特征。</p>
                <p>综合分 {evaluation.total_score ?? '无法评分'}{evaluation.total_score != null && ' / 100'}</p>
                <ul className="list-disc pl-5">
                  {scoreKeys.map((key) => <li key={key}>{scoreFields[key]}：{evaluation[key] ?? '待确认'} / 10，权重 {result.study.weights[key]}%</li>)}
                </ul>
                <p>0 / 5 / 10 对应低 / 中 / 高程度。综合分中，不利程度与条件负担的分值取反，应对条件分值越高代表前提越充分。</p>
                {evaluation.confidence != null && <p>模型自评 {evaluation.confidence}，未经校准。</p>}
                {evaluation.evidence && <p className="break-words">模型评分说明：{evaluation.evidence}</p>}
              </div>
            </details>
          )}
          {incomplete > 0 && <p className="text-sm text-muted-foreground">{incomplete} 个情景的实验评分未完成或不可用。</p>}
        </section>
      </div>
    </div>
  )
}
