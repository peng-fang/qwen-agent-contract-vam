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
export type Material = { file?: File; text?: string; evidence?: VamEvidenceInput[] }

export async function runChecklist(role: string, material: Material) {
  const body = new FormData()
  body.append('role', role)
  if (material.file) body.append('file', material.file)
  if (material.text) body.append('text', material.text)
  if (material.evidence?.length) body.append('evidence', JSON.stringify(material.evidence))
  return (await axios.post<ChecklistResult>('/api/checklist/run', body)).data
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
