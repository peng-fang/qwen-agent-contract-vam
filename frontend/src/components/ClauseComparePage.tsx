import { useMemo, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  extractClauses,
  resolveEvidence,
  type ClauseMatch,
  type ClauseSide,
  type ClauseExtractionResult,
} from '@/lib/api'
import { EvidenceDrawer, type EvidenceDetail } from './EvidenceDrawer'

const CLAUSE_ORDER = [
  'refund',
  'penalty',
  'auto_renewal',
  'service_term',
  'extra_fee',
] as const

const CLAUSE_LABEL: Record<(typeof CLAUSE_ORDER)[number], string> = {
  refund: '退款',
  penalty: '违约金',
  auto_renewal: '自动续费/续租',
  service_term: '服务期限',
  extra_fee: '额外收费',
}

function compact(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

function EvidenceCell({
  side,
  file,
  onOpen,
  onResolve,
}: {
  side: ClauseSide | null | undefined
  file?: File | null
  onOpen: (evidence: EvidenceDetail, file?: File | null) => void
  onResolve: (evidenceId: string) => void
}) {
  if (!side || !side.evidences.length) {
    return <span className="text-sm text-muted-foreground">未找到相关原文</span>
  }
  const shown = side.evidences.slice(0, 2)
  return (
    <div className="space-y-2">
      {shown.map((evidence) => (
        <div
          key={`${evidence.document_id}-${evidence.char_start}`}
          className="space-y-1 rounded-md border border-transparent p-1"
        >
          <button
            type="button"
            className="w-full space-y-1 rounded-md text-left transition-colors hover:bg-accent/60"
            onClick={() =>
              onOpen(
                {
                  quote: evidence.quote,
                  filename: evidence.filename,
                  page: evidence.page,
                  clauseLabel: side.fields.clause_ref || undefined,
                  evidenceId: evidence.evidence_id,
                },
                file,
              )
            }
            aria-label={`查看第 ${evidence.page} 页证据原文`}
          >
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <Badge variant="secondary">第 {evidence.page} 页</Badge>
              <span className="truncate">{evidence.filename}</span>
              {evidence.quote.length > 0 && side.fields.clause_ref && (
                <span>· {side.fields.clause_ref}</span>
              )}
            </div>
            <blockquote
              title={compact(evidence.quote)}
              className="line-clamp-3 rounded-md border border-border bg-muted/60 px-2.5 py-2 text-xs leading-5"
            >
              {compact(evidence.quote)}
            </blockquote>
            <div className="text-xs font-medium text-blue-600">查看原文 →</div>
          </button>
          <div className="flex items-center justify-between gap-2 px-1 text-[11px] text-muted-foreground">
            <span className="break-all font-mono">{evidence.evidence_id}</span>
            <button
              type="button"
              className="shrink-0 text-blue-600 hover:underline"
              onClick={() => onResolve(evidence.evidence_id)}
            >
              按 ID 回查
            </button>
          </div>
        </div>
      ))}
      {side.evidences.length > shown.length && (
        <div className="text-xs text-muted-foreground">
          另有 {side.evidences.length - shown.length} 处原文
        </div>
      )}
    </div>
  )
}

function MatchRow({
  clauseType,
  match,
  promoFile,
  contractFile,
  onOpen,
  onResolve,
}: {
  clauseType: string
  match?: ClauseMatch
  promoFile?: File | null
  contractFile?: File | null
  onOpen: (evidence: EvidenceDetail, file?: File | null) => void
  onResolve: (evidenceId: string) => void
}) {
  const verdict = match?.verdict
  const conflict = verdict === 'conflict'
  const label = match?.clause_label ?? CLAUSE_LABEL[clauseType as (typeof CLAUSE_ORDER)[number]]
  const groupVariant =
    match?.verdict_group === 'conflict'
      ? 'red'
      : match?.verdict_group === 'consistent'
        ? 'green'
        : 'secondary'

  return (
    <tr className={conflict ? 'bg-red-50/70' : undefined}>
      <td
        className={`border-t border-border p-3 align-top ${
          conflict ? 'border-l-4 border-l-red-500' : ''
        }`}
      >
        <div className="font-medium">{label}</div>
        {conflict && <div className="mt-1 text-xs font-medium text-red-600">重点冲突</div>}
      </td>
      <td className="border-t border-border p-3 align-top">
        {match ? (
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant={groupVariant}>{match.verdict_group_label}</Badge>
              <span className="text-xs text-muted-foreground">细分：{match.verdict_label}</span>
            </div>
            {match.reasons.length > 0 && (
              <ul className="space-y-1 text-xs leading-5 text-muted-foreground">
                {match.reasons.slice(0, 3).map((reason) => (
                  <li key={reason}>· {reason}</li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <span className="text-sm text-muted-foreground">尚未比对</span>
        )}
      </td>
      <td className="border-t border-border p-3 align-top">
        <EvidenceCell side={match?.promo} file={promoFile} onOpen={onOpen} onResolve={onResolve} />
      </td>
      <td className="border-t border-border p-3 align-top">
        <EvidenceCell
          side={match?.contract}
          file={contractFile}
          onOpen={onOpen}
          onResolve={onResolve}
        />
      </td>
    </tr>
  )
}

export function ClauseComparePage() {
  const [promoFile, setPromoFile] = useState<File | null>(null)
  const [contractFile, setContractFile] = useState<File | null>(null)
  const [result, setResult] = useState<ClauseExtractionResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [evidence, setEvidence] = useState<EvidenceDetail | null>(null)
  const [evidenceFile, setEvidenceFile] = useState<File | null>(null)

  function openEvidence(detail: EvidenceDetail, file?: File | null) {
    setEvidence(detail)
    setEvidenceFile(file ?? null)
  }

  async function resolveById(evidenceId: string) {
    setError('')
    try {
      const resolved = await resolveEvidence(evidenceId)
      openEvidence(
        {
          quote: resolved.quote,
          filename: resolved.filename,
          page: resolved.page,
          clauseLabel: '按 ID 反查',
          evidenceId: resolved.evidence_id,
          verified: resolved.verified,
        },
        null,
      )
    } catch {
      setError(`按 ID 回查失败：${evidenceId} 不在已登记的材料中，或字符区间已失效。`)
    }
  }

  const counts = useMemo(() => {
    const counter = { conflict: 0, insufficient: 0, consistent: 0 }
    result?.matches.forEach((item) => {
      if (item.verdict_group === 'conflict') counter.conflict += 1
      else if (item.verdict_group === 'consistent') counter.consistent += 1
      else counter.insufficient += 1
    })
    return counter
  }, [result])

  async function run() {
    setError('')
    if (!promoFile || !contractFile) {
      setError('请同时选择宣传材料和合同。')
      return
    }
    setLoading(true)
    try {
      const data = await extractClauses([promoFile, contractFile], ['promo', 'contract'])
      setResult(data)
    } catch (e) {
      setResult(null)
      const detail = e instanceof Error ? e.message : '请求失败'
      setError(
        `无法连接条款对照服务（${detail}）。请确认后端已在 8001 端口启动；` +
          '本页不会影响合同核验与推演功能。',
      )
    } finally {
      setLoading(false)
    }
  }

  const rows = CLAUSE_ORDER.map((clauseType) => ({
    clauseType,
    match: result?.matches.find((item) => item.clause_type === clauseType),
  }))

  return (
    <div className="space-y-6">
      <Card className="border-0 bg-gradient-to-br from-slate-50 to-blue-50 shadow-sm">
        <CardContent className="p-6">
          <h1 className="text-2xl font-bold tracking-tight">宣传 vs 合同</h1>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            上传宣传材料与合同，逐类比对退款、违约金、自动续费、服务期限、额外收费；
            结论与金额由确定性代码判定，原文片段可回查页码。
          </p>
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle>风险评分与红线</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <Badge
                variant={
                  result.risk.level === 'high'
                    ? 'red'
                    : result.risk.level === 'medium'
                      ? 'yellow'
                      : 'green'
                }
              >
                {result.risk.level_label}
              </Badge>
              <span className="text-2xl font-semibold">
                {result.risk.score}
                <span className="text-sm font-normal text-muted-foreground"> / 100</span>
              </span>
              <span className="text-xs text-muted-foreground">
                确定性规则评分，不构成法律意见
              </span>
            </div>
            {result.risk.redlines.length > 0 ? (
              <ul className="space-y-1.5 text-sm">
                {result.risk.redlines.map((item) => (
                  <li key={`${item.clause_type}-${item.reason}`} className="flex gap-2">
                    <Badge
                      variant={
                        item.severity === 'high'
                          ? 'red'
                          : item.severity === 'medium'
                            ? 'yellow'
                            : 'secondary'
                      }
                    >
                      {item.clause_label}
                    </Badge>
                    <span className="text-muted-foreground">{item.reason}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-sm text-muted-foreground">未发现需要重点提示的红线。</div>
            )}
            <div className="text-xs text-muted-foreground">
              证据复核：{result.evidence_review.passed}/{result.evidence_review.checked} 条通过
              {result.evidence_review.failed > 0 &&
                `，${result.evidence_review.failed} 条需检查`}
              （确定性偏移与字段重算校验）
            </div>
            {result.evidence_review.failures.length > 0 && (
              <ul className="space-y-1 text-xs text-red-600">
                {result.evidence_review.failures.map((failure) => (
                  <li key={failure.evidence_id}>
                    · {failure.clause_label}：{failure.problems.join('；')}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>选择两份材料</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">宣传材料</span>
              <input
                type="file"
                accept=".pdf,.txt,.md"
                className="block w-full text-sm text-muted-foreground"
                onChange={(e) => setPromoFile(e.target.files?.[0] ?? null)}
              />
              <span className="block truncate text-xs text-muted-foreground">
                {promoFile ? promoFile.name : '例如 demo_data/promo_gym.pdf'}
              </span>
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">合同</span>
              <input
                type="file"
                accept=".pdf,.txt,.md"
                className="block w-full text-sm text-muted-foreground"
                onChange={(e) => setContractFile(e.target.files?.[0] ?? null)}
              />
              <span className="block truncate text-xs text-muted-foreground">
                {contractFile ? contractFile.name : '例如 demo_data/contract_gym.pdf'}
              </span>
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={run} disabled={loading}>
              {loading ? '对照中…' : '开始对照'}
            </Button>
            {result && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge variant="red">矛盾 {counts.conflict}</Badge>
                <Badge variant="yellow">证据不足/未约定 {counts.insufficient}</Badge>
                <Badge variant="green">一致 {counts.consistent}</Badge>
                <span className="text-xs text-muted-foreground">
                  抽取方式：{result.extractor === 'rules+llm' ? '规则 + 模型' : '规则'}
                </span>
              </div>
            )}
          </div>

          {error && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {error}
            </div>
          )}
          {result?.warnings.length ? (
            <ul className="space-y-1 text-xs text-muted-foreground">
              {result.warnings.map((warning) => (
                <li key={warning}>· {warning}</li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>五类条款逐项对照</CardTitle>
        </CardHeader>
        <CardContent>
          {!result && !error && (
            <div className="mb-4 rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
              尚未开始对照。选择宣传材料和合同后点击「开始对照」；
              若后端未启动，这里会给出可读提示而不会报错。
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] border-collapse text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="w-32 p-3 font-medium">条款</th>
                  <th className="w-56 p-3 font-medium">结论</th>
                  <th className="p-3 font-medium">宣传材料</th>
                  <th className="p-3 font-medium">合同</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ clauseType, match }) => (
                  <MatchRow
                    key={clauseType}
                    clauseType={clauseType}
                    match={match}
                    promoFile={promoFile}
                    contractFile={contractFile}
                    onOpen={openEvidence}
                    onResolve={resolveById}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <EvidenceDrawer
        open={Boolean(evidence)}
        evidence={evidence}
        file={evidenceFile}
        onClose={() => {
          setEvidence(null)
          setEvidenceFile(null)
        }}
      />
    </div>
  )
}
