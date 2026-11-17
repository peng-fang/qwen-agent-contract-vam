import axios from 'axios'
import type { VamConsequence, VamEvidenceInput } from './api'

export const fieldClass = 'min-h-11 w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary'

export type Priority = 'must_confirm' | 'should_confirm' | 'reference'
export type Source = { id: string; filename: string; page: number | null; kind: 'pdf' | 'text'; quote: string }
export type ChecklistItem = {
  id: string; title: string; trigger: string; consequence: string; question: string; topic: string
  priority: Priority | null; evidence: Source[]; priority_source?: 'rule' | 'intern' | null; priority_confidence?: number | null
}
export type ChecklistResult = {
  items: ChecklistItem[]; priority_model: string | null; warning: string | null; scope: string; source_count: number
}
export type Material = { file?: File; files?: File[]; text?: string; evidence?: VamEvidenceInput[] }
export type ChecklistProgress = { stage: string; status: 'running' | 'done' | 'warning'; detail: string }

export function checklistBody(role: string, material: Material) {
  const body = new FormData()
  body.append('role', role)
  if (material.file) body.append('file', material.file)
  for (const file of material.files ?? []) body.append('files', file)
  if (material.text) body.append('text', material.text)
  if (material.evidence?.length) body.append('evidence', JSON.stringify(material.evidence))
  return body
}

export async function runChecklist(role: string, material: Material) {
  return (await axios.post<ChecklistResult>('/api/checklist/run', checklistBody(role, material))).data
}

export async function runChecklistStream(
  role: string,
  material: Material,
  onProgress?: (event: ChecklistProgress) => void,
  onPartial?: (items: ChecklistItem[]) => void,
  signal?: AbortSignal,
) {  const response = await fetch('/api/checklist/run/stream', {
    method: 'POST',
    body: checklistBody(role, material),
    signal,
  })
  if (!response.ok || !response.body) {
    const raw = await response.text().catch(() => '')
    throw new Error(raw || `请求失败（${response.status}）`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const dataLine = block.split('\n').find((line) => line.startsWith('data:'))
      if (!dataLine) continue
      const payload = JSON.parse(dataLine.slice(5).trim()) as {
        type: string
        stage?: string
        status?: 'running' | 'done' | 'warning'
        detail?: string
        items?: ChecklistItem[]
        result?: ChecklistResult
      }
      if (payload.type === 'progress' && payload.stage && payload.status) {
        onProgress?.({ stage: payload.stage, status: payload.status, detail: payload.detail ?? '' })
      } else if (payload.type === 'partial' && Array.isArray(payload.items)) {
        onPartial?.(payload.items.map((item) => ({ ...item, priority: item.priority ?? null })))
      } else if (payload.type === 'result' && payload.result) {
        return payload.result
      } else if (payload.type === 'error') {
        throw new Error(payload.detail || '生成清单失败')
      }
    }
  }
  throw new Error('清单流意外结束，请重试。')
}

export async function exportChecklistPdf(items: ChecklistItem[], role: string, scope: string) {
  const response = await axios.post('/api/checklist/export', { items, role, scope }, { responseType: 'blob' })
  return response.data as Blob
}

export type ConsequenceTemplate = 'lease_exit' | 'repurchase'
export type Estimate = Omit<VamConsequence, 'action_id' | 'effect'> & { label: string }

export async function estimateConsequence(template: ConsequenceTemplate, parameters: Record<string, string | boolean>) {
  return (await axios.post<Estimate[]>('/api/checklist/consequence', { template, parameters })).data
}

export function checklistError(error: unknown) {
  if (axios.isAxiosError(error)) {
    const reason: unknown = error.response?.data?.detail
    if (typeof reason === 'string') return reason
    if (Array.isArray(reason)) return '请检查输入长度、文件及原文来源。'
  }
  return '处理失败，请稍后重试。'
}
