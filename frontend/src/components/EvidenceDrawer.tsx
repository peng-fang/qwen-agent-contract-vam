import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { resolveEvidence, type RelatedEvidence } from '@/lib/api'
import { PdfViewer } from './PdfViewer'

export interface EvidenceDetail {
  quote: string
  filename?: string
  page?: number | null
  clauseLabel?: string
  evidenceId?: string
  verified?: boolean
}

interface Props {
  open: boolean
  evidence: EvidenceDetail | null
  file?: File | null
  onClose: () => void
  showRelated?: boolean
}

export function EvidenceDrawer({ open, evidence, file, onClose, showRelated }: Props) {
  const evidenceId = showRelated && open ? evidence?.evidenceId : undefined
  const [lookup, setLookup] = useState<{ id: string; result?: RelatedEvidence } | null>(null)
  const [selection, setSelection] = useState<string | null>(null)
  const relatedLookup = lookup?.id === evidenceId ? lookup : null
  const focus = relatedLookup?.result?.related.find((item) => item.evidence_id === selection)

  useEffect(() => {
    if (!evidenceId) return
    let active = true
    void resolveEvidence(evidenceId, true).then(
      (value) => { if (active) setLookup({ id: evidenceId, result: value.related_evidence }) },
      () => { if (active) setLookup({ id: evidenceId }) },
    )
    return () => { active = false }
  }, [evidenceId])

  useEffect(() => {
    if (!open) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open || !evidence) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/45 p-4 sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label="证据原文"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-4xl rounded-xl border border-border bg-background shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-border p-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">证据原文</h2>
              {evidence.clauseLabel && <Badge variant="secondary">{evidence.clauseLabel}</Badge>}
              {typeof evidence.page === 'number' && (
                <Badge variant="yellow">第 {evidence.page} 页</Badge>
              )}
              {evidence.verified && <Badge variant="green">后端按 ID 校验通过</Badge>}
            </div>
            <div className="mt-1 truncate text-xs text-muted-foreground">
              {evidence.filename || '模型输入片段'}
            </div>
            {evidence.evidenceId && (
              <div className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
                {evidence.evidenceId}
              </div>
            )}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="关闭证据">
            ✕
          </Button>
        </div>

        <div className="space-y-4 p-4">
          <blockquote className="whitespace-pre-wrap rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-950">
            {evidence.quote}
          </blockquote>

          {evidenceId && (
            <section className="space-y-2" aria-label="可能关联的条件与条款">
              <h3 className="text-sm font-semibold">可能关联的条件与条款</h3>
              {!relatedLookup && <p className="text-xs text-muted-foreground">正在回查原文…</p>}
              {relatedLookup && !relatedLookup.result && (
                <p className="text-xs text-muted-foreground">暂时无法回查关联原文。</p>
              )}
              {relatedLookup?.result?.related.map((item) => (
                <div key={item.evidence_id} className="space-y-1 rounded-md border p-2">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="secondary">第 {item.page} 页</Badge>
                    <span>{item.relation === 'reference' ? '条号引用' : '相邻限定句'}</span>
                    {file && <button type="button" className="text-blue-600 hover:underline"
                      onClick={() => setSelection(item.evidence_id)}>定位原文</button>}
                  </div>
                  <p className="whitespace-pre-wrap text-sm">{item.quote}</p>
                </div>
              ))}
              {relatedLookup?.result && !relatedLookup.result.related.length && !relatedLookup.result.omitted && (
                <p className="text-xs text-muted-foreground">未找到可识别的相邻限定句或条号引用。</p>
              )}
              {Boolean(relatedLookup?.result?.omitted) && (
                <p className="text-xs text-muted-foreground">还有片段超出本次展示范围，请结合原文核对。</p>
              )}
            </section>
          )}

          {file ? (
            <div className="overflow-hidden rounded-md border border-border">
              {focus && <Button variant="ghost" size="sm" onClick={() => setSelection(null)}>返回主证据</Button>}
              <PdfViewer
                file={file}
                matches={[]}
                focusPage={focus?.page ?? evidence.page ?? null}
                highlightText={focus?.quote ?? evidence.quote}
              />
            </div>
          ) : (
            <div className="rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
              这条依据来自模型输入片段，尚未关联到合同 PDF 页码；上传合同后可在 PDF 中回查。
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
