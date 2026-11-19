import { useEffect, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { type RentalRisk } from '@/lib/api'
import { openConversation, askReport, workflowError, type Conversation } from '@/lib/workflows'
import type { AskRiskContext } from './RentalReviewPanel'

interface AskAssistantDrawerProps {
  open: boolean
  reportId: string | null
  context: AskRiskContext | null
  risks: RentalRisk[]
  files: File[]
  onClose: () => void
}

export function AskAssistantDrawer({ open, reportId, context, risks, onClose }: AskAssistantDrawerProps) {
  const [messages, setMessages] = useState<Conversation['messages']>([])
  const [chat, setChat] = useState<Conversation | null>(null)
  const activeChat = useRef('')
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const selectedRisks = selectedIds
    .map((id) => risks.find((risk) => risk.risk_id === id))
    .filter((risk): risk is RentalRisk => Boolean(risk))
  const primary = selectedRisks[0] ?? context
  const primaryRiskId = selectedRisks[0]?.risk_id ?? context?.riskId
  const contextTitle = selectedRisks.length > 1 ? `已引用 ${selectedRisks.length} 条风险做对比` : primary?.title

  useEffect(() => {
    if (!open) return
    let active = true
    activeChat.current = ''
    setChat(null)
    setMessages([])
    setLoading(false)
    setError('')
    if (reportId) {
      openConversation(reportId).then((data) => {
        if (!active) return
        activeChat.current = data.id
        setChat(data); setMessages(data.messages)
      }).catch((e) => { if (active) setError(workflowError(e)) })
    } else setError('请重新生成审查报告后再追问。')
    setInput(context?.question ?? '')
    setSelectedIds(context?.riskId ? [context.riskId] : [])
    const timer = window.setTimeout(() => inputRef.current?.focus(), 100)
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      active = false
      activeChat.current = ''
      window.clearTimeout(timer)
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [open, reportId, context?.riskId, context?.question])

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, loading, open])

  function toggleRisk(riskId: string) {
    setSelectedIds((prev) => {
      if (prev.includes(riskId)) {
        return prev.length === 1 ? prev : prev.filter((id) => id !== riskId)
      }
      return [...prev, riskId]
    })
  }

  async function send() {
    const question = input.trim()
    if (!question || loading) return
    if (!chat) {
      setError('正在恢复对话，请稍后重试；如尚未审查，请先生成报告。')
      return
    }
    setError('')
    setInput('')
    setLoading(true)
    try {
      const result = await askReport(chat, question, selectedIds)
      if (activeChat.current !== result.id) return
      setChat(result); setMessages(result.messages)
    } catch (err) {
      if (activeChat.current === chat.id) { setInput(question); setError(workflowError(err)) }
    } finally {
      if (activeChat.current === chat.id) setLoading(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="合同问题助手">
      <button
        type="button"
        aria-label="关闭助手"
        className="absolute inset-0 bg-slate-950/30 backdrop-blur-[1px]"
        onClick={onClose}
      />
      <aside className="absolute inset-x-0 bottom-0 flex h-[88vh] w-full flex-col overflow-hidden rounded-t-2xl border border-border bg-background shadow-2xl sm:inset-y-0 sm:left-auto sm:right-0 sm:h-full sm:max-w-[460px] sm:rounded-none sm:border-l">
        <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <div className="text-sm font-semibold">问助手</div>
            <div className="text-xs text-muted-foreground">带着这条风险继续追问</div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
        </header>

        {primary && (
          <section className="max-h-[32vh] shrink-0 overflow-auto border-b border-amber-200 bg-amber-50 px-4 py-3 text-amber-950">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant="yellow">来自合同审查</Badge>
              {primary.page && <span>第 {primary.page} 页</span>}
              {primaryRiskId && <span>{primaryRiskId}</span>}
              {selectedRisks.length > 1 && <Badge variant="secondary">对比模式</Badge>}
            </div>
            <div className="mt-2 text-sm font-semibold">{contextTitle}</div>
            <blockquote className="mt-1 rounded border border-amber-200 bg-white/70 px-2 py-1.5 text-xs leading-5">
              {primary.quote}
            </blockquote>
            <p className="mt-2 text-xs leading-5">
              <span className="font-medium">风险：</span>
              {primary.explanation}
            </p>
            {primary.suggestion && (
              <p className="mt-1 text-xs leading-5">
                <span className="font-medium">建议：</span>
                {primary.suggestion}
              </p>
            )}
          </section>
        )}

        {risks.length > 1 && (
          <section className="max-h-[24vh] shrink-0 overflow-auto border-b border-border bg-muted/30 px-4 py-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="text-xs font-medium">引用风险（可选）</div>
              <div className="text-[11px] text-muted-foreground">已选 {selectedRisks.length} 条</div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {risks.map((risk) => {
                const selected = selectedIds.includes(risk.risk_id)
                return (
                  <button
                    key={risk.risk_id}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => toggleRisk(risk.risk_id)}
                    className={
                      selected
                        ? 'rounded-full border border-blue-600 bg-blue-600 px-2.5 py-1 text-left text-[11px] leading-4 text-white'
                        : 'rounded-full border border-border bg-background px-2.5 py-1 text-left text-[11px] leading-4 text-muted-foreground hover:border-blue-300 hover:text-foreground'
                    }
                  >
                    <span className="mr-1 opacity-70">{risk.severity === 'high' ? '高' : risk.severity === 'medium' ? '中' : '低'}</span>
                    {risk.title}
                  </button>
                )
              })}
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              默认只引用当前风险；点选其他风险可一起对比，发送时会带入所选风险原文。
            </p>
          </section>
        )}

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
          {messages.length === 0 && (
            <div className="rounded-lg border border-dashed border-border p-3 text-sm leading-6 text-muted-foreground">
              可以直接发送下面的问题，或继续追问“这条风险怎么谈”“合同应该怎么改”“如果对方不同意怎么办”。
            </div>
          )}
          {messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              className={
                message.role === 'user'
                  ? 'ml-8 rounded-lg bg-blue-600 px-3 py-2 text-sm leading-6 text-white'
                  : 'mr-4 rounded-lg border border-border bg-muted/60 px-3 py-2 text-sm leading-6'
              }
            >
              <div className="mb-1 text-[11px] opacity-70">{message.role === 'user' ? '你' : '助手'}</div>
              <div className="whitespace-pre-wrap break-words">{message.content}
              {message.citations?.map((citation) => <details key={citation.id} className="mt-2 text-xs"><summary>来源 [{citation.id}]{citation.page ? ` · 第${citation.page}页` : ''}</summary><p>{citation.quote ?? citation.summary}</p></details>)}</div>
              {message.riskTitles && message.riskTitles.length > 1 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {message.riskTitles.map((title) => (
                    <span key={title} className="rounded-full bg-white/20 px-2 py-0.5 text-[10px]">
                      {title}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="mr-4 rounded-lg border border-border bg-muted/60 px-3 py-2 text-sm text-muted-foreground">
              助手正在结合合同原文回答…
            </div>
          )}
          <div ref={endRef} />
        </div>

        <footer className="shrink-0 border-t border-border p-3">
          {error && <div className="mb-2 text-xs text-red-600">{error}</div>}
          <Textarea
            ref={inputRef}
            rows={3}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                event.preventDefault()
                void send()
              }
            }}
            placeholder="追问这条风险，例如：如果对方不同意修改，我还有什么退路？"
          />
          <div className="mt-2 flex items-center justify-between gap-2">
            <span className="text-[11px] text-muted-foreground">Ctrl / ⌘ + Enter 发送</span>
            <Button onClick={() => void send()} disabled={loading || !input.trim() || !chat}>
              {loading ? '回答中…' : '发送'}
            </Button>
          </div>
          <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
            回答结合当前报告、原文及最近8轮对话；历史记录保存在后端。仅作风险提示。
          </p>
        </footer>
      </aside>
    </div>
  )
}
