import { useEffect, useMemo, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  reviewRentalContractStream,
  type RentalContractType,
  type RentalRegion,
  type RentalReviewProgress,
  type RentalReviewResult,
  type RentalRisk,
} from '@/lib/api'
import { EvidenceDrawer, type EvidenceDetail } from './EvidenceDrawer'

const SEVERITY_LABEL = { high: '高风险', medium: '中风险', low: '低风险' } as const
const SEVERITY_VARIANT = { high: 'red', medium: 'yellow', low: 'green' } as const
const STATUS_LABEL = { supported: '证据支持', needs_review: '待人工复核', rejected: '已驳回' } as const
const STATUS_VARIANT = { supported: 'green', needs_review: 'yellow', rejected: 'red' } as const

const STAGE_LABELS: Record<string, string> = {
  parse: '合同解析',
  classify: '合同分类',
  rules: '规则基线',
  analyze: '条款理解 / 风险审查',
  cross: '交叉验证',
  legal: '法律检索',
  judge: 'Judge 复核',
  cache: '结果缓存',
  done: '完成',
}
const STAGE_ORDER = ['parse', 'classify', 'rules', 'analyze', 'cross', 'legal', 'judge', 'done']

export interface AskRiskContext {
  question: string
  riskId: string
  title: string
  quote: string
  explanation: string
  suggestion: string
  page: number | null
  severity: RentalRisk['severity']
  status: RentalRisk['status']
}

type ResolvedContractType = Exclude<RentalContractType, 'auto'>

const BASE_FACT_LABELS: Record<string, string> = {
  party_a: '甲方',
  party_b: '乙方',
  price: '价款/费用',
  deposit: '押金/保证金',
  term: '期限',
  renewal: '续约',
  termination: '解除',
  penalty: '违约金',
  delivery: '交付',
  repair: '维修/质保',
  refund: '退款/退货',
  other_fees: '其他费用',
}

const FACT_LABELS_BY_TYPE: Record<ResolvedContractType, Record<string, string>> = {
  rental: {
    ...BASE_FACT_LABELS,
    party_a: '出租人',
    party_b: '承租人',
    price: '租金',
    term: '租赁期限',
    renewal: '续租',
    termination: '解除/收回',
    repair: '维修',
  },
  consumer: {
    ...BASE_FACT_LABELS,
    party_a: '经营者',
    party_b: '消费者',
    price: '课程/服务费',
    deposit: '定金/押金',
    term: '课程/会员期限',
    renewal: '续费/续课',
    termination: '退课/解除',
    repair: '服务/售后',
    refund: '退款/退费',
  },
  procurement: {
    ...BASE_FACT_LABELS,
    party_a: '采购方',
    party_b: '供应方',
    price: '合同价款',
    term: '交付/服务期限',
    renewal: '续约',
    delivery: '交付/验收',
    repair: '质保/保修',
  },
  labor: {
    ...BASE_FACT_LABELS,
    party_a: '用人单位',
    party_b: '劳动者',
    price: '工资',
    deposit: '押金/保证金',
    term: '合同期限',
    renewal: '续签',
    termination: '解除/终止',
    penalty: '违约金/罚款',
  },
  loan: {
    ...BASE_FACT_LABELS,
    party_a: '借款人',
    party_b: '出借人',
    price: '本金',
    deposit: '保证金',
    term: '借款期限',
    renewal: '续贷',
    termination: '提前到期/解除',
    penalty: '罚息/违约金',
    delivery: '放款',
    repair: '担保',
  },
  ecommerce: {
    ...BASE_FACT_LABELS,
    party_a: '商家/平台',
    party_b: '消费者',
    price: '商品价款',
    term: '服务期限',
    renewal: '自动续费',
    termination: '解除/退款',
    delivery: '配送',
    repair: '售后',
    refund: '退货/退款',
  },
  franchise: {
    ...BASE_FACT_LABELS,
    party_a: '特许人',
    party_b: '被特许人',
    price: '加盟费',
    deposit: '保证金',
    term: '合同期限',
    renewal: '续约',
    termination: '退出/解除',
    delivery: '培训/支持',
    repair: '供货/设备',
  },
  dispute: {
    ...BASE_FACT_LABELS,
    price: '争议金额',
    term: '合同期限',
    termination: '争议解决',
    delivery: '通知送达',
    repair: '费用承担',
  },
}

const CONTRACT_TYPE_LABELS: Record<RentalContractType, string> = {
  auto: '自动识别',
  rental: '住宅租赁',
  consumer: '健身/培训',
  procurement: '采购/买卖',
  labor: '劳动合同',
  loan: '借款/担保',
  ecommerce: '消费/电商',
  franchise: '加盟/特许经营',
  dispute: '争议解决',
}

function RiskCard({
  risk,
  onOpen,
  onAsk,
}: {
  risk: RentalRisk
  onOpen: (evidence: EvidenceDetail) => void
  onAsk?: (context: AskRiskContext) => void
}) {
  return (
    <div className="rounded-lg border border-border bg-background p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={SEVERITY_VARIANT[risk.severity]}>{SEVERITY_LABEL[risk.severity]}</Badge>
            <h3 className="font-semibold">{risk.title}</h3>
            {risk.status === 'needs_review' && <Badge variant="yellow">待复核</Badge>}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {risk.clause_ids.join('、')}
            {risk.page ? ` · 第 ${risk.page} 页` : ''}
            {` · 置信度 ${risk.confidence > 0 ? `${(risk.confidence * 100).toFixed(0)}%` : '待定'}`}
            {risk.source === 'cross_rule' ? ' · 跨条款规则' : ''}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {onAsk && (
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                onAsk({
                  question: `请结合合同原文解释这个风险：「${risk.title}」。原文是：「${risk.quote}」。这个条款对我有什么影响，合同应该怎么改？`,
                  riskId: risk.risk_id,
                  title: risk.title,
                  quote: risk.quote,
                  explanation: risk.explanation,
                  suggestion: risk.suggestion,
                  page: risk.page,
                  severity: risk.severity,
                  status: risk.status,
                })
              }
            >
              带着问题问助手
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              onOpen({
                quote: risk.quote,
                filename: risk.clause_ids.join('、'),
                page: risk.page,
                clauseLabel: risk.title,
              })
            }
          >
            查看原文
          </Button>
        </div>
      </div>

      <blockquote className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-950">
        {risk.quote}
      </blockquote>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          <div className="text-xs font-medium text-muted-foreground">为什么有风险</div>
          <p className="mt-1 text-sm leading-6">{risk.explanation}</p>
        </div>
        <div>
          <div className="text-xs font-medium text-muted-foreground">签约前怎么问 / 怎么改</div>
          <p className="mt-1 text-sm leading-6">{risk.suggestion || '要求对方把该条款写清楚，并保留书面确认。'}</p>
        </div>
      </div>

      <div className="mt-3 rounded-md border border-border bg-muted/40 p-3">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-medium">法律依据</span>
          <Badge variant={STATUS_VARIANT[risk.status]}>{STATUS_LABEL[risk.status]}</Badge>
        </div>
        {risk.legal_basis.length ? (
          <ul className="mt-2 space-y-2">
            {risk.legal_basis.map((law) => (
              <li key={law.article_id} className="text-sm leading-6">
                <div className="mb-1 flex flex-wrap items-center gap-1.5">
                  <Badge variant={law.source_type === 'official_web' ? 'yellow' : 'secondary'}>
                    {law.source_type === 'official_web' ? '官方网页' : '本地法律库'}
                  </Badge>
                  {law.verified === false && <Badge variant="red">待复核</Badge>}
                </div>
                <a
                  href={law.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-blue-700 underline"
                >
                  {law.source}{law.article}「{law.title}」
                </a>
                <div className="text-muted-foreground">{law.summary}</div>
                <div className="text-xs text-muted-foreground">
                  {law.note}
                  {law.retrieved_at ? ` · 抓取于 ${law.retrieved_at.slice(0, 10)}` : ''}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">
            未检索到明确法律依据，已标记为待人工复核，不强行下结论。
          </p>
        )}
        {risk.judge_reason && (
          <p className="mt-2 text-xs text-muted-foreground">Judge：{risk.judge_reason}</p>
        )}
      </div>
    </div>
  )
}

export function RentalReviewPanel({
  files,
  onAsk,
}: {
  files: File[]
  onAsk?: (context: AskRiskContext, risks: RentalRisk[]) => void
}) {
  const [result, setResult] = useState<RentalReviewResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [fastMode, setFastMode] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [progress, setProgress] = useState<Record<string, RentalReviewProgress>>({})
  const abortRef = useRef<AbortController | null>(null)
  const [error, setError] = useState('')
  const [evidence, setEvidence] = useState<EvidenceDetail | null>(null)
  const [region, setRegion] = useState<RentalRegion>('mainland')
  const [contractType, setContractType] = useState<RentalContractType>('auto')

  const targetFile = useMemo(
    () => files.find((f) => /\.(pdf|docx|txt|md)$/i.test(f.name)) ?? null,
    [files],
  )
  const pdfFile = useMemo(
    () => files.find((f) => /\.pdf$/i.test(f.name)) ?? null,
    [files],
  )

  async function run() {
    setError('')
    setResult(null)
    if (!targetFile) {
      setError('请先上传一份合同（PDF / DOCX / TXT）。')
      return
    }
    setLoading(true)
    setProgress({})
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const data = await reviewRentalContractStream(
        targetFile,
        contractType,
        region,
        !fastMode,
        (event) => setProgress((prev) => ({ ...prev, [event.stage]: event })),
        controller.signal,
      )
      setResult(data)
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      const message = e instanceof Error ? e.message : '审查失败'
      setError(`风险审查失败：${message}。请确认后端已启动；如果模型不可用，会退回规则审查。`)
    } finally {
      abortRef.current = null
      setLoading(false)
    }
  }

  function cancel() {
    abortRef.current?.abort()
    abortRef.current = null
    setLoading(false)
  }

  useEffect(() => {
    if (!loading) {
      setElapsed(0)
      return
    }
    const startedAt = Date.now()
    setElapsed(0)
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [loading])

  function chooseRegion(next: RentalRegion) {
    if (next === region) return
    setRegion(next)
    setResult(null)
    setEvidence(null)
    setError('')
  }

  function chooseContractType(next: RentalContractType) {
    if (next === contractType) return
    setContractType(next)
    setResult(null)
    setEvidence(null)
    setError('')
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>合同风险审查</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              {region === 'mainland' ? '中国内地' : '中国香港'} · {CONTRACT_TYPE_LABELS[contractType]} ·
              条款理解 / 风险审查 / 法律检索 / 交叉验证 / Judge 多 Agent 流水线。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">类型</span>
            <select
              value={contractType}
              onChange={(e) => chooseContractType(e.target.value as RentalContractType)}
              disabled={loading}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-xs"
              aria-label="合同类型"
            >
              {(Object.keys(CONTRACT_TYPE_LABELS) as RentalContractType[]).map((key) => (
                <option key={key} value={key}>
                  {CONTRACT_TYPE_LABELS[key]}
                </option>
              ))}
            </select>
            <span className="text-xs text-muted-foreground">法域</span>
            <div className="inline-flex overflow-hidden rounded-md border border-border">
              <button
                type="button"
                onClick={() => chooseRegion('mainland')}
                disabled={loading}
                className={`px-3 py-1.5 text-xs transition-colors ${
                  region === 'mainland'
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-background text-muted-foreground hover:bg-accent'
                }`}
              >
                中国内地
              </button>
              <button
                type="button"
                onClick={() => chooseRegion('hongkong')}
                disabled={loading}
                className={`px-3 py-1.5 text-xs transition-colors ${
                  region === 'hongkong'
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-background text-muted-foreground hover:bg-accent'
                }`}
              >
                中国香港
              </button>
            </div>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground" title="跳过模型分析，只跑规则和本地/网页法律检索，通常几秒完成">
              <input
                type="checkbox"
                checked={fastMode}
                onChange={(e) => setFastMode(e.target.checked)}
                disabled={loading}
                className="accent-blue-600"
              />
              快速模式
            </label>
            <Button onClick={run} disabled={loading || !targetFile}>
              {loading ? '多 Agent 审查中…' : '开始风险审查'}
            </Button>
            {loading && (
              <Button variant="outline" onClick={cancel}>
                取消
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {region === 'hongkong' && (
          <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800">
            当前按香港法例检索（Cap. 7 / Cap. 458 / Cap. 26），不会混用中国内地《民法典》条文。
          </div>
        )}
        {!targetFile && (
          <div className="rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
            先在下方的「上传材料」选择一份合同。审查只针对单份合同，不会把宣传材料当成合同。
          </div>
        )}
        {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        {loading && (
          <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800" aria-live="polite">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>{progress.cache ? '命中审查缓存，正在整理结果…' : '正在运行合同风险审查流水线。'}</span>
              <span className="font-mono text-xs">已等待 {elapsed}s</span>
            </div>
            <div className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
              {STAGE_ORDER.map((stage) => {
                const event = progress[stage]
                const skipped = fastMode && stage === 'analyze'
                const marker = skipped ? '跳过' : event?.status === 'done' ? '✓' : event?.status === 'warning' ? '!' : event?.status === 'running' ? '…' : '·'
                return (
                  <div key={stage} className={event?.status === 'done' ? 'text-blue-800' : 'text-blue-600/70'}>
                    <span className="mr-1 inline-block w-5 font-mono">{marker}</span>
                    {STAGE_LABELS[stage] ?? stage}
                    {event?.detail && event.status !== 'done' ? ` · ${event.detail}` : ''}
                  </div>
                )
              })}
            </div>
            <div className="mt-1 text-xs text-blue-700">
              {fastMode
                ? '快速模式：正在生成初步风险提示，请稍候。'
                : '正在逐条检查合同条款并匹配适用法律，请稍候。'}
            </div>
          </div>
        )}

        {result && (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge variant="secondary">{result.region_label}</Badge>
              <Badge variant="secondary">{result.contract_type_label}</Badge>
              {result.contract_type_requested === 'auto' && (
                <Badge variant="yellow">
                  自动识别 · 置信度 {(result.classification.confidence * 100).toFixed(0)}%
                </Badge>
              )}
              {result.classification.known_type === false && (
                <Badge variant="secondary">未知类型 · 低风险限流</Badge>
              )}
              {result.cache_hit && <Badge variant="secondary">缓存结果</Badge>}
              <span className="text-muted-foreground">
                共 {result.summary.total_risks} 条 · {result.page_count} 页 · {result.clause_count} 条条款 ·
                法律依据按该法域和合同类型检索
              </span>
            </div>
            {result.classification.legal_domains.length > 0 && (
              <div className="text-xs text-muted-foreground">
                识别到的法律领域：{result.classification.legal_domains.join('、')}
              </div>
            )}
            <div className="grid gap-3 rounded-lg border border-border bg-muted/30 p-4 md:grid-cols-4">
              <div>
                <div className="text-xs text-muted-foreground">总体风险</div>
                <div className="mt-1 text-2xl font-bold">{result.summary.risk_level_label}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">风险分</div>
                <div className="mt-1 text-2xl font-bold">{result.summary.risk_score} / 100</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">高风险 / 中风险</div>
                <div className="mt-1 text-2xl font-bold">
                  {result.summary.high_count} / {result.summary.medium_count}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">待人工复核</div>
                <div className="mt-1 text-2xl font-bold">{result.summary.needs_review_count}</div>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {Object.entries(result.facts).map(([key, value]) => {
                const label = FACT_LABELS_BY_TYPE[result.contract_type][key]
                if (!value || Array.isArray(value) || !label) return null
                return (
                  <div key={key} className="rounded-md border border-border px-3 py-2 text-sm">
                    <div className="text-xs text-muted-foreground">{label}</div>
                    <div className="mt-1 break-words">{String(value)}</div>
                  </div>
                )
              })}
            </div>

            <div className="flex flex-wrap gap-2">
              {result.agent_trace.map((step) => (
                <span
                  key={`${step.agent}-${step.detail}`}
                  className="rounded-full border border-border bg-background px-3 py-1 text-xs text-muted-foreground"
                  title={step.detail}
                >
                  {step.agent} · {step.status}
                </span>
              ))}
            </div>

            {result.warnings.length > 0 && (
              <ul className="space-y-1 text-xs text-amber-700">
                {result.warnings.map((warning) => (
                  <li key={warning}>· {warning}</li>
                ))}
              </ul>
            )}

            <div className="space-y-3">
              {result.risks.length ? (
                result.risks.map((risk) => (
                  <RiskCard
                    key={risk.risk_id}
                    risk={risk}
                    onOpen={setEvidence}
                    onAsk={(context) => onAsk?.(context, result.risks)}
                  />
                ))
              ) : (
                <div className="rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
                  未发现需要提示的风险条款；仍建议人工通读全文。
                </div>
              )}
            </div>

            <div className="text-xs leading-5 text-muted-foreground">{result.disclaimer}</div>
          </>
        )}

        <EvidenceDrawer
          open={Boolean(evidence)}
          evidence={evidence}
          file={pdfFile}
          onClose={() => setEvidence(null)}
        />
      </CardContent>
    </Card>
  )
}
