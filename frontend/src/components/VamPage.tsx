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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { deepenVam, exportVam, runVam, type VamResult, type VamTreeNode } from '@/lib/api'

function riskColor(risk: number): string {
  if (risk >= 7) return '#fee2e2'
  if (risk >= 4) return '#fef3c7'
  return '#dcfce7'
}

function buildGraph(tree: VamResult['tree']) {
  const nodes: Node[] = []
  const edges: Edge[] = []
  let order = 0

  function walk(node: VamTreeNode, depth: number, parentId?: string) {
    const y = order * 130
    order += 1
    const risk = node.evaluation?.risk ?? node._risk ?? 5
    nodes.push({
      id: node.id,
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
        id: `${parentId}-${node.id}`,
        source: parentId,
        target: node.id,
        type: 'smoothstep',
        markerEnd: { type: MarkerType.ArrowClosed },
      })
    }
    node.children?.forEach((c) => walk(c, depth + 1, node.id))
  }

  tree.branches.forEach((b) => walk(b, 0))
  return { nodes, edges }
}

const EXAMPLES = [
  '创业者 A 融资 1000 万元，签对赌：3 年内净利润累计达到 3000 万元；否则按年化 8% 回购投资人股份，或向投资人补偿股权。行业处于扩张期，请推演 3 年后可能的结局和最优策略。',
  '某消费品牌以 1.2 亿元估值融资 3000 万元，签对赌：3 年内累计营收达到 2 亿元且完成 IPO 申报；否则按年化 12% 回购，或向投资人补偿股权。请推演 3 年后可能的结局和最优策略。',
]

export function VamPage() {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<VamResult | null>(null)
  const [history, setHistory] = useState<VamResult[]>([])
  const [selectedLeaf, setSelectedLeaf] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [report, setReport] = useState('')

  const graph = useMemo(() => (result ? buildGraph(result.tree) : { nodes: [], edges: [] }), [result])

  async function run() {
    setError('')
    setResult(null)
    setReport('')
    if (!query.trim()) {
      setError('请输入对赌条款或决策背景。')
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
      <Card>
        <CardHeader>
          <CardTitle>对赌协议推演</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm leading-6 text-muted-foreground">
            输入对赌条款或关键决策背景，系统用两个 Agent 先生成情景分支、再打分排序，最后渲染成可展开的决策树。
            结果只是情景推演，不是真实预测，也不构成投资或法律建议。
          </p>
          <Textarea
            placeholder="例如：创业者融资 1000 万，签对赌：3 年净利润累计达到 3000 万，否则年化 8% 回购或股权补偿。"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              className="bg-orange-500 text-white hover:bg-orange-600"
              onClick={run}
              disabled={loading}
            >
              {loading ? '推演中…' : '开始推演'}
            </Button>
            <select
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
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
            <Button variant="secondary" onClick={deepen} disabled={!result || loading}>
              继续推演
            </Button>
            <Button variant="outline" onClick={back} disabled={!result}>
              回溯
            </Button>
            <Button variant="outline" onClick={download} disabled={!result}>
              导出报告
            </Button>
          </div>
          {error && <div className="text-sm text-red-600">{error}</div>}
        </CardContent>
      </Card>

      {result && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>推荐路径</CardTitle>
            </CardHeader>
            <CardContent className="text-sm">
              <div>
                <span className="font-medium">{result.best.path?.join(' → ')}</span>
                {'（' + result.best.branch + '）'} — 总分 {result.best.total_score} / 100
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>分支评分排序</CardTitle>
            </CardHeader>
            <CardContent>
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="bg-muted">
                    <th className="border border-border px-2 py-1 text-left">排序</th>
                    <th className="border border-border px-2 py-1 text-left">分支</th>
                    <th className="border border-border px-2 py-1 text-left">总分</th>
                    <th className="border border-border px-2 py-1 text-left">风险</th>
                    <th className="border border-border px-2 py-1 text-left">概率</th>
                  </tr>
                </thead>
                <tbody>
                  {result.ranked.map((r, i) => (
                    <tr key={r.leaf_id}>
                      <td className="border border-border px-2 py-1">{i + 1}</td>
                      <td className="border border-border px-2 py-1">{r.branch}</td>
                      <td className="border border-border px-2 py-1">{r.total_score}</td>
                      <td className="border border-border px-2 py-1">
                        <Badge variant={r.risk >= 7 ? 'red' : r.risk >= 4 ? 'yellow' : 'green'}>
                          {r.risk}
                        </Badge>
                      </td>
                      <td className="border border-border px-2 py-1">{r.probability}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>决策树</CardTitle>
            </CardHeader>
            <CardContent>
              <div style={{ height: 520 }}>
                <ReactFlow nodes={graph.nodes} edges={graph.edges} fitView>
                  <Background />
                  <Controls />
                </ReactFlow>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle>下载报告</CardTitle>
        </CardHeader>
        <CardContent>
          {report ? (
            <a
              className="text-sm font-medium text-blue-600 underline"
              href={`data:text/markdown;charset=utf-8,${encodeURIComponent(report)}`}
              download="vam_report.md"
            >
              下载 Markdown 报告
            </a>
          ) : (
            <p className="text-sm text-muted-foreground">
              推演完成后点击「导出报告」生成 Markdown 文件。
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>原始 JSON（调试用）</CardTitle>
        </CardHeader>
        <CardContent>
          <details>
            <summary className="cursor-pointer text-sm text-muted-foreground">展开 / 收起</summary>
            <pre className="mt-3 max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs">
              {result ? JSON.stringify(result, null, 2) : '（暂无数据）'}
            </pre>
          </details>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">示例</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {EXAMPLES.map((e) => (
            <button
              key={e}
              className="w-full rounded-md border border-border px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
              onClick={() => setQuery(e)}
            >
              {e}
            </button>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
