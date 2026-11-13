import { useMemo, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { analyzeContract, searchEvidence, type EvidenceMatch } from '@/lib/api'
import { BrandLogo } from './BrandLogo'
import { PdfViewer } from './PdfViewer'

const PLUGINS = [
  { name: 'contract-calculate_refund', desc: '退款金额计算' },
  { name: 'contract-calculate_total_cost', desc: '总成本计算' },
  { name: 'contract-calculate_lease_upfront', desc: '租房首期计算' },
]

const SUGGESTIONS = [
  '退款条款：宣传承诺与合同条款是否一致？请引用原文和页码。',
  '违约金条款：合同如何约定？请引用原文和页码。',
  '自动续费条款：是否存在自动续费/自动续租？如何取消？',
  '服务期限条款：合同期限多长？与宣传材料是否一致？',
  '额外收费条款：除主费用外还有哪些收费？请计算总成本。',
]

interface ContractPageProps {
  onOpenVam: () => void
}

export function ContractPage({ onOpenVam }: ContractPageProps) {
  const [files, setFiles] = useState<File[]>([])
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [resultFiles, setResultFiles] = useState<string[]>([])
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [searchText, setSearchText] = useState('')
  const [matches, setMatches] = useState<EvidenceMatch[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const questionRef = useRef<HTMLTextAreaElement>(null)

  const fileOptions = useMemo(
    () => files.map((f, i) => ({ label: f.name, value: i })),
    [files],
  )

  async function run() {
    setError('')
    setAnswer('')
    setMatches([])
    setResultFiles([])
    if (!question.trim()) {
      setError('请输入要核验的问题。')
      return
    }
    if (!files.length) {
      setError('请选择至少一个文件。')
      return
    }
    setLoading(true)
    try {
      const res = await analyzeContract(question, files)
      setAnswer(res.answer)
      setResultFiles(res.files)
      setSelectedIndex(0)
    } catch (e) {
      setError(e instanceof Error ? e.message : '请求失败')
    } finally {
      setLoading(false)
    }
  }

  async function locate() {
    setError('')
    if (!resultFiles.length) {
      setError('请先完成一次核验。')
      return
    }
    if (!searchText.trim()) {
      setError('请输入要定位的原文关键词。')
      return
    }
    try {
      const m = await searchEvidence(resultFiles[selectedIndex], searchText)
      setMatches(m)
    } catch (e) {
      setError(e instanceof Error ? e.message : '定位失败')
    }
  }

  function chooseSuggestion(text: string) {
    setQuestion(text)
    questionRef.current?.focus()
  }

  return (
    <div className="space-y-6">
      <Card className="border-0 bg-gradient-to-br from-slate-50 to-blue-50 shadow-sm">
        <CardContent className="flex flex-col items-start gap-5 p-6 sm:flex-row sm:items-center">
          <BrandLogo size={96} className="shrink-0" />
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold tracking-tight">签之前</h1>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              上传宣传材料与合同，先核对月租/押金/总价/手续费，再核验五类条款并计算金额。
            </p>
          </div>
          <Button
            className="w-full bg-gradient-to-r from-blue-600 to-indigo-600 sm:w-auto"
            onClick={onOpenVam}
          >
            🚀 打开合同情景推演与决策评分 →
          </Button>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_890px]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>上传材料</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="block w-full text-sm text-muted-foreground"
                onChange={(e) => {
                  setFiles(Array.from(e.target.files ?? []))
                  setMatches([])
                  setResultFiles([])
                }}
              />
              {files.length > 0 && (
                <div className="text-sm text-muted-foreground">
                  已选 {files.length} 个文件：{files.map((f) => f.name).join('、')}
                </div>
              )}
              <Textarea
                ref={questionRef}
                placeholder="例如：请核验退款承诺，并引用原文和页码。"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
              />
              <Button onClick={run} disabled={loading}>
                {loading ? '核验中…' : '开始核验'}
              </Button>
              {error && <div className="text-sm text-red-600">{error}</div>}
              {answer && (
                <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">{answer}</pre>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">插件</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {PLUGINS.map((p) => (
                <label
                  key={p.name}
                  className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm"
                >
                  <input type="checkbox" checked readOnly className="accent-blue-600" />
                  <span className="font-mono text-xs">{p.name}</span>
                  <span className="text-muted-foreground">· {p.desc}</span>
                </label>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">推荐对话</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => chooseSuggestion(s)}
                  className="w-full rounded-md border border-border px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
                >
                  {s}
                </button>
              ))}
            </CardContent>
          </Card>
        </div>

        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>证据定位（PDF 高亮）</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <select
                className="rounded-md border border-border bg-background px-2 py-1 text-sm"
                value={selectedIndex}
                onChange={(e) => setSelectedIndex(Number(e.target.value))}
              >
                {fileOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <input
                className="rounded-md border border-border bg-background px-2 py-1 text-sm"
                placeholder="输入原文关键词，例如：手续费"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
              />
              <Button variant="secondary" onClick={locate}>
                定位并高亮
              </Button>
            </div>
            <div className="text-sm text-muted-foreground">
              {matches.length ? (
                <>
                  <Badge variant="yellow">找到 {matches.length} 处</Badge>
                  <span className="ml-2">黄色高亮即为原文位置。</span>
                </>
              ) : (
                '完成核验后，输入关键词可在 PDF 中定位原文。'
              )}
            </div>
            <PdfViewer file={files[selectedIndex]} matches={matches} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
