import { useEffect, useMemo, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  extractClauses,
  type ClauseMatch,
  type ClauseSide,
  type ClauseVerdict,
  type ClauseExtractionResult,
  type VamEvidenceInput,
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

const VERDICT_VARIANT: Record<ClauseVerdict, 'green' | 'red' | 'yellow' | 'secondary'> = {
  consistent: 'green',
  conflict: 'red',
  missing_in_contract: 'yellow',
  missing_in_promo: 'yellow',
  missing_both: 'secondary',
  unclear: 'secondary',
}

const VERDICT_LABEL: Record<ClauseVerdict, string> = {
  consistent: '一致',
  conflict: '矛盾',
  missing_in_contract: '合同未约定',
  missing_in_promo: '宣传未提及',
  missing_both: '双方未约定',
  unclear: '证据不足',
}

function compact(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

function matchEvidence(match?: ClauseMatch, fileIds?: Map<string, string>): VamEvidenceInput[] {
  if (!match) return []
  const seen = new Set<string>()
  const items: VamEvidenceInput[] = []
  for (const side of [match.promo, match.contract]) {
    for (const evidence of side?.evidences ?? []) {
      const fileId = fileIds?.get(evidence.document_id)
      if (!fileId || !/^[a-f0-9]{32}\.pdf$/i.test(fileId)) continue
      if (!evidence.page || !evidence.quote.trim()) continue
      const key = `${fileId}:${evidence.page}:${evidence.quote}`
      if (seen.has(key)) continue
      seen.add(key)
      items.push({
        file_id: fileId,
        filename: evidence.filename,
        page: evidence.page,
        quote: evidence.quote.slice(0, 2400),
      })
    }
  }
  return items.slice(0, 6)
}

function EvidenceCell({
  side,
  file,
  onOpen,
}: {
  side: ClauseSide | null | undefined
  file?: File | null
  onOpen: (evidence: EvidenceDetail, file?: File | null) => void
}) {
  if (!side || !side.evidences.length) {
    return <span className="text-sm text-muted-foreground">未找到相关原文</span>
  }
  const shown = side.evidences.slice(0, 2)
  return (
    <div className="space-y-2">
      {shown.map((evidence) => (
        <button
          key={`${evidence.document_id}-${evidence.char_start}`}
          type="button"
          className="w-full space-y-1 rounded-md border border-transparent p-1 text-left transition-colors hover:border-border hover:bg-accent/60"
          onClick={() =>
            onOpen(
              {
                quote: evidence.quote,
                filename: evidence.filename,
                page: evidence.page,
                clauseLabel: side.fields.clause_ref || undefined,
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
  fileIds,
  checklistEvidence,
  onOpen,
  onAdd,
  onRemove,
}: {
  clauseType: string
  match?: ClauseMatch
  promoFile?: File | null
  contractFile?: File | null
  fileIds?: Map<string, string>
  checklistEvidence?: VamEvidenceInput[]
  onOpen: (evidence: EvidenceDetail, file?: File | null) => void
  onAdd?: (items: VamEvidenceInput[]) => void
  onRemove?: (evidence: VamEvidenceInput) => void
}) {
  const verdict = match?.verdict
  const conflict = verdict === 'conflict'
  const label = match?.clause_label ?? CLAUSE_LABEL[clauseType as (typeof CLAUSE_ORDER)[number]]
  const evidence = matchEvidence(match, fileIds)
  const canAdd = Boolean(onAdd && evidence.length && verdict && verdict !== 'consistent')
  const added = Boolean(evidence.length && evidence.every((item) => checklistEvidence?.some((existing) =>
    existing.file_id === item.file_id && existing.page === item.page && existing.quote === item.quote)))

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
            <Badge variant={VERDICT_VARIANT[match.verdict]}>
              {VERDICT_LABEL[match.verdict]}
            </Badge>
            {match.reasons.length > 0 && (
              <ul className="space-y-1 text-xs leading-5 text-muted-foreground">
                {match.reasons.slice(0, 3).map((reason) => (
                  <li key={reason}>· {reason}</li>
                ))}
              </ul>
            )}
            {canAdd && (
              <Button
                type="button"
                size="sm"
                variant={added ? 'secondary' : 'outline'}
                onClick={() => {
                  if (added) {
                    evidence.forEach((item) => onRemove?.(item))
                  } else {
                    onAdd?.(evidence)
                  }
                }}
              >
                {added ? '已加入必问清单' : '加入必问清单'}
              </Button>
            )}
          </div>
        ) : (
          <span className="text-sm text-muted-foreground">尚未比对</span>
        )}
      </td>
      <td className="border-t border-border p-3 align-top">
        <EvidenceCell side={match?.promo} file={promoFile} onOpen={onOpen} />
      </td>
      <td className="border-t border-border p-3 align-top">
        <EvidenceCell side={match?.contract} file={contractFile} onOpen={onOpen} />
      </td>
    </tr>
  )
}

export function ClauseComparePage({
  sharedFiles = [],
  onFilesChange,
  checklistEvidence = [],
  onAddChecklist,
  onRemoveChecklist,
}: {
  sharedFiles?: File[]
  onFilesChange?: (files: File[]) => void
  checklistEvidence?: VamEvidenceInput[]
  onAddChecklist?: (items: VamEvidenceInput[]) => void
  onRemoveChecklist?: (evidence: VamEvidenceInput) => void
}) {
  const [promoFile, setPromoFile] = useState<File | null>(null)
  const [contractFile, setContractFile] = useState<File | null>(null)
  const [result, setResult] = useState<ClauseExtractionResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [evidence, setEvidence] = useState<EvidenceDetail | null>(null)
  const [evidenceFile, setEvidenceFile] = useState<File | null>(null)

  useEffect(() => {
    if (!sharedFiles.length) return
    setPromoFile((current) => current ?? sharedFiles.find((file) => /promo|宣传/i.test(file.name)) ?? sharedFiles[0] ?? null)
    setContractFile((current) => current ?? sharedFiles.find((file) => /contract|合同/i.test(file.name)) ?? sharedFiles[1] ?? sharedFiles[0] ?? null)
  }, [sharedFiles])

  function rememberFiles(next: File[]) {
    onFilesChange?.([...sharedFiles.filter((file) => !next.some((item) => item.name === file.name)), ...next])
  }

  function openEvidence(detail: EvidenceDetail, file?: File | null) {
    setEvidence(detail)
    setEvidenceFile(file ?? null)
  }

  const counts = useMemo(() => {
    const counter = { conflict: 0, missing: 0, consistent: 0 }
    result?.matches.forEach((item) => {
      if (item.verdict === 'conflict') counter.conflict += 1
      else if (item.verdict === 'consistent') counter.consistent += 1
      else counter.missing += 1
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
  const fileIds = useMemo(() => new Map(
    (result?.documents ?? []).map((document) => [document.document_id, document.file_id ?? '']),
  ), [result])

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
                onChange={(e) => {
                  const selected = e.target.files?.[0] ?? null
                  setPromoFile(selected)
                  if (selected) rememberFiles([selected])
                }}
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
                onChange={(e) => {
                  const selected = e.target.files?.[0] ?? null
                  setContractFile(selected)
                  if (selected) rememberFiles([selected])
                }}
              />
              <span className="block truncate text-xs text-muted-foreground">
                {contractFile ? contractFile.name : '例如 demo_data/contract_gym.pdf'}
              </span>
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {sharedFiles.length > 0 && (
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setPromoFile(sharedFiles.find((file) => /promo|宣传/i.test(file.name)) ?? sharedFiles[0])
                  setContractFile(sharedFiles.find((file) => /contract|合同/i.test(file.name)) ?? sharedFiles[1] ?? sharedFiles[0])
                }}
              >
                使用工作区文件
              </Button>
            )}
            <Button onClick={run} disabled={loading}>
              {loading ? '对照中…' : '开始对照'}
            </Button>
            {result && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge variant="red">矛盾 {counts.conflict}</Badge>
                <Badge variant="yellow">缺失/未提及 {counts.missing}</Badge>
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
                    fileIds={fileIds}
                    checklistEvidence={checklistEvidence}
                    onOpen={openEvidence}
                    onAdd={onAddChecklist}
                    onRemove={onRemoveChecklist}
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
