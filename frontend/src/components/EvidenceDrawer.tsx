import { useEffect } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
}

export function EvidenceDrawer({ open, evidence, file, onClose }: Props) {
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

          {file ? (
            <div className="overflow-hidden rounded-md border border-border">
              <PdfViewer
                file={file}
                matches={[]}
                focusPage={evidence.page ?? null}
                highlightText={evidence.quote}
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
