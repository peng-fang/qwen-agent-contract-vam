import { useMemo, useState } from 'react'
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { deepenVam, exportVam, runVam, type VamResult, type VamTreeNode } from '@/lib/api'
import { EvidenceDrawer, type EvidenceDetail } from './EvidenceDrawer'

const EVIDENCE_EXAMPLE =
  '某消费品牌以 1.5 亿元估值融资 3000 万元，签 3 年对赌：3 年内累计营收达到 2 亿元且完成 IPO 申报，否则按年化 10% 回购，或以股权补偿；若逾期回购，另按未付金额每日 0.05% 支付违约金。品牌当前年营收 4000 万元，账上现金 2500 万元，行业增速放缓。请推演 3 年后可能情景，并对每个分支评估违约风险、落地可行性、预期损失和依据。'

const EXAMPLES = [
  EVIDENCE_EXAMPLE,
  '创业者 A 融资 1000 万元，签对赌：3 年内净利润累计达到 3000 万元；否则按年化 8% 回购投资人股份，或向投资人补偿股权。行业处于扩张期，请推演 3 年后可能的结局和最优策略。',
  '某消费品牌以 1.2 亿元估值融资 3000 万元，签对赌：3 年内累计营收达到 2 亿元且完成 IPO 申报；否则按年化 12% 回购，或向投资人补偿股权。请推演 3 年后可能的结局和最优策略。',
]

function riskColor(risk: number): string {
  if (risk >= 7) return '#fee2e2'
  if (risk >= 4) return '#fef3c7'
  return '#dcfce7'
}

function buildGraph(tree: VamResult['tree']) {
  const nodes: Node[] = []
  const edges: Edge[] = []
  const seenIds = new Set<string>()
  let order = 0

  function walk(node: VamTreeNode, depth: number, parentId?: string) {
    const y = order * 130
    order += 1
    let uniqueId = node.id
    let suffix = 0
    while (seenIds.has(uniqueId)) {
      suffix += 1
      uniqueId = `${node.id}-${suffix}`
    }
    seenIds.add(uniqueId)
    const risk = node.evaluation?.risk_score ?? node._risk ?? 5
    nodes.push({
      id: uniqueId,
      position: { x: depth * 280, y },
      data: {
        label: node.branch,
        risk,
        score: node.evaluation?.total_score ?? null,
      },
      style: {
        background: riskColor(risk),
        border: '1px solid #e5e7eb',
        borderRadius: 8,
        padding: '10px 12px',
        width: 200,
        fontSize: 13,
      },
    })
    if (parentId) {
      edges.push({
        id: `${parentId}-${uniqueId}`,
        source: parentId,
        target: uniqueId,
        type: 'smoothstep',
        markerEnd: { type: MarkerType.ArrowClosed },
      })
    }
    node.children?.forEach((c) => walk(c, depth + 1, uniqueId))
  }

  const rootId = '__scenario_root__'
  seenIds.add(rootId)
  const rootY = Math.max(0, (tree.branches.length - 1) * 65)
  nodes.push({
    id: rootId,
    position: { x: 0, y: rootY },
    data: { label: '合同情景', risk: 5, score: null },
    style: {
      background: '#f1f5f9',
      border: '1px solid #cbd5e1',
      borderRadius: 8,
      padding: '10px 12px',
      width: 160,
      fontSize: 13,
      fontWeight: 600,
      color: '#334155',
    },
  })
  tree.branches.forEach((b) => walk(b, 1, rootId))
  return { nodes, edges }
}

export function VamPage() {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<VamResult | null>(null)
  const [history, setHistory] = useState<VamResult[]>([])
  const [selectedLeaf, setSelectedLeaf] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [report, setReport] = useState('')
  const [evidence, setEvidence] = useState<EvidenceDetail | null>(null)

  const graph = useMemo(() => (result ? buildGraph(result.tree) : { nodes: [], edges: [] }), [result])

  async function run() {
    setError('')
    setResult(null)
    setReport('')
    if (!query.trim()) {
      setError('请输入要推演的对赌条款或决策背景。')
      return
    }
    setLoading(true)
    try {
      const res = await runVam(query)
      setResult(res)
      setHistory([])
      setSelectedLeaf(res.ranked[0]?.leaf_id ?? '')
    } catch (e) {
      setError(e instanceof Error ? e.message : '推演失败')
    } finally {
      setLoading(false)
    }
  }

  async function deepen() {
    if (!result || !selectedLeaf) return
    setLoading(true)
    setError('')
    try {
      const res = await deepenVam(result, selectedLeaf)
      setHistory((h) => [...h, result])
      setResult(res)
      setSelectedLeaf(res.ranked[0]?.leaf_id ?? '')
    } catch (e) {
      setError(e instanceof Error ? e.message : '展开失败')
    } finally {
      setLoading(false)
    }
  }

  function back() {
    if (!history.length) {
      setError('已经是最初结果。')
      return
    }
    setError('')
    const prev = history[history.length - 1]
    setHistory(history.slice(0, -1))
    setResult(prev)
    setSelectedLeaf(prev.ranked[0]?.leaf_id ?? '')
  }

  async function download() {
    if (!result) return
    try {
      const md = await exportVam(result)
      setReport(md)
    } catch (e) {
      setError(e instanceof Error ? e.message : '导出失败')
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">合同情景推演与决策评分</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          输入对赌条款或关键决策背景，系统用两个 Agent 先生成情景分支、再打分排序，最后渲染成可展开的决策树。
          结果只是情景推演，不是真实预测，也不构成投资或法律建议。
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,560px)_minmax(0,1fr)]">
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-background p-4 shadow-sm">
            <label className="mb-1 block text-sm font-medium">对赌条款 / 决策背景</label>
            <Textarea
              className="min-h-[170px]"
              placeholder="例：融资 1000 万，3 年净利润对赌 3000 万，否则年化 8% 回购或股权补偿……"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button
              className="mt-4 w-full bg-orange-500 text-white hover:bg-orange-600"
              onClick={run}
              disabled={loading}
            >
              {loading ? '推演中…' : '开始推演'}
            </Button>

            <label className="mb-1 mt-4 block text-sm font-medium">选择叶子分支</label>
            <select
              className="h-9 w-full rounded-md border border-border bg-background px-2 text-sm"
              value={selectedLeaf}
              onChange={(e) => setSelectedLeaf(e.target.value)}
              disabled={!result}
            >
              {result?.ranked.map((r) => (
                <option key={r.leaf_id} value={r.leaf_id}>
                  {r.path.join(' → ')}｜{r.branch}
                </option>
              ))}
            </select>

            <div className="mt-3 grid grid-cols-2 gap-3">
              <Button variant="secondary" onClick={deepen} disabled={!result || loading}>
                沿此分支继续推演
              </Button>
              <Button variant="secondary" onClick={back} disabled={!result}>
                回溯一步
              </Button>
            </div>

            <Button className="mt-3 w-full" variant="secondary" onClick={download} disabled={!result}>
              导出 Markdown 报告
            </Button>

            <div className="mt-4 min-h-[170px] rounded-md border border-dashed border-border p-3">
              <div className="text-xs text-muted-foreground">📄 下载报告</div>
              <div className="mt-10 text-center">
                {report ? (
                  <a
                    className="text-sm font-medium text-blue-600 underline"
                    href={`data:text/markdown;charset=utf-8,${encodeURIComponent(report)}`}
                    download="vam_report.md"
                  >
                    下载 Markdown 报告
                  </a>
                ) : (
                  <span className="text-4xl text-muted-foreground/40">📄</span>
                )}
              </div>
            </div>

            <div className="mt-4">
              <h2 className="text-lg font-semibold">结果</h2>
              {!result ? (
                <p className="mt-1 text-sm text-muted-foreground">（等待输入）</p>
              ) : (
                <div className="mt-2 space-y-2 text-sm">
                  <div>
                    <span className="font-medium">推荐路径：</span>
                    {result.best.path?.join(' → ')}（{result.best.branch}） — 总分{' '}
                    {result.best.total_score} / 100
                  </div>
                  <table className="w-full border-collapse text-xs">
                    <thead>
                      <tr className="bg-muted">
                        <th className="border border-border px-2 py-1 text-left">排序</th>
                        <th className="border border-border px-2 py-1 text-left">分支</th>
                        <th className="border border-border px-2 py-1 text-left">总分</th>
                        <th className="border border-border px-2 py-1 text-left">违约风险</th>
                        <th className="border border-border px-2 py-1 text-left">可行性</th>
                        <th className="border border-border px-2 py-1 text-left">预期损失</th>
                        <th className="border border-border px-2 py-1 text-left">置信度</th>
                        <th className="border border-border px-2 py-1 text-left">依据</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.ranked.map((r, i) => (
                        <tr key={r.leaf_id}>
                          <td className="border border-border px-2 py-1">{i + 1}</td>
                          <td className="border border-border px-2 py-1">{r.branch}</td>
                          <td className="border border-border px-2 py-1">{r.total_score}</td>
                          <td className="border border-border px-2 py-1">
                            <Badge
                              variant={
                                r.risk_score === null
                                  ? 'secondary'
                                  : r.risk_score >= 7
                                    ? 'red'
                                    : r.risk_score >= 4
                                      ? 'yellow'
                                      : 'green'
                              }
                            >
                              {r.risk_score === null ? '信息不足' : r.risk_score}
                            </Badge>
                          </td>
                          <td className="border border-border px-2 py-1">
                            {r.feasibility_score === null ? '信息不足' : r.feasibility_score}
                          </td>
                          <td className="border border-border px-2 py-1">
                            {r.loss_score === null ? '信息不足' : r.loss_score}
                          </td>
                          <td className="border border-border px-2 py-1">
                            {r.confidence === null ? '信息不足' : r.confidence}
                          </td>
                          <td className="border border-border px-2 py-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-1.5 text-xs text-blue-600"
                              onClick={() =>
                                setEvidence({
                                  quote: `${r.evidence || '【信息不足，无法评估】'}\n\n合同输入：${result.query}`,
                                  filename: '模型输入片段',
                                  page: null,
                                  clauseLabel: '评分依据',
                                })
                              }
                            >
                              查看
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <details className="mt-4 rounded-md border border-border">
              <summary className="cursor-pointer px-3 py-2 text-sm text-muted-foreground">
                原始 JSON（调试用）
              </summary>
              <pre className="max-h-72 overflow-auto border-t border-border p-3 text-xs">
                {result ? JSON.stringify(result, null, 2) : '（暂无数据）'}
              </pre>
            </details>

            {error && <div className="mt-3 text-sm text-red-600">{error}</div>}
          </div>
        </div>

        <div className="min-w-0">
          <div className="h-[640px] rounded-lg border border-border bg-background shadow-sm">
            {result ? (
              <ReactFlow nodes={graph.nodes} edges={graph.edges} fitView>
                <Background />
                <Controls />
              </ReactFlow>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                决策树将在这里显示
              </div>
            )}
          </div>
        </div>
      </div>

      <div>
        <h2 className="mb-2 text-base font-semibold">示例</h2>
        <div className="space-y-2">
          {EXAMPLES.map((e) => (
            <button
              key={e}
              className="w-full rounded-md border border-border px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
              onClick={() => setQuery(e)}
            >
              {e}
            </button>
          ))}
        </div>
      </div>

      <EvidenceDrawer
        open={Boolean(evidence)}
        evidence={evidence}
        onClose={() => setEvidence(null)}
      />
    </div>
  )
}
