import axios from 'axios'
import type { ClauseExtractionResult, ClauseMatch, RiskAssessment } from './api'

export function workflowError(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((d) => `${d.loc?.slice(-1)[0] ?? ''}：${d.msg}`).join('；')
  }
  return error instanceof Error ? error.message : '请求失败'
}

export interface Conversation {
  id: string; revision: number; report_id: string
  messages: { role: 'user' | 'assistant'; content: string; riskTitles?: string[];
    citations?: { id: string; quote?: string; text?: string; summary?: string; page?: number; source_url?: string }[] }[]
}
export async function openConversation(reportId: string): Promise<Conversation> {
  const key = `report-chat:${reportId}`
  const previous = localStorage.getItem(key)
  if (previous) {
    try { return (await axios.get<Conversation>(`/api/workflows/conversations/${previous}`)).data }
    catch (error) {
      if (!axios.isAxiosError(error) || error.response?.status !== 404) throw error
      localStorage.removeItem(key)
    }
  }
  const data = (await axios.post<Conversation>('/api/workflows/conversations', { report_id: reportId })).data
  localStorage.setItem(key, data.id)
  return data
}
export async function askReport(chat: Conversation, question: string, riskIds: string[]) {
  return (await axios.post<Conversation>(`/api/workflows/conversations/${chat.id}/messages`,
    { question, risk_ids: riskIds, revision: chat.revision })).data
}

export type RefundFact = 'used_sessions' | 'total_paid' | 'unit_price' | 'request_day' | 'request_phase'

export interface Verification extends ClauseExtractionResult {
  task_id?: string; task_revision?: number; confirmed_facts?: Record<string, string | number>
  refund_question?: { field: RefundFact; question: string; condition: string | null; evidence_id: string | null } | null
  semantic_review?: { items: { clause_type: string; original_verdict: string; verdict: string; reason: string;
    evidence: { evidence_id: string; quote: string; page: number }[] }[];
    matches: ClauseMatch[]; risk: RiskAssessment; model: { provider: string; model: string }; note: string } | null
}
export async function loadVerification(id: string) {
  return (await axios.get<Verification>(`/api/workflows/verifications/${id}`)).data
}
export async function updateFacts(task: Verification, facts: Record<string, string | number>) {
  return (await axios.post<Verification>(`/api/workflows/verifications/${task.task_id}/facts`,
    { revision: task.task_revision, facts })).data
}
export async function reviewVerification(task: Verification) {
  return (await axios.post<Verification>(`/api/workflows/verifications/${task.task_id}/review`,
    { revision: task.task_revision })).data
}

export interface PaymentPlan {
  title: string; currency: string; payer: string; confirmed: boolean; origin: string
  source_filename?: string; sources?: { page: number; quote: string }[]
  installments: { due_date: string; amount: string; label: string }[]
}
export interface PaymentRecord {
  id: string; revision: number; plans: PaymentPlan[]; history: { revision: number }[]
  comparison: { currency: string; payer: string; dates: string[];
    plans: { title: string; total: string; points: { date: string; payment: string; cumulative: string }[] }[] }
}
export async function savePayments(plans: PaymentPlan[], record: PaymentRecord | null) {
  return (await axios.post<PaymentRecord>('/api/workflows/payments',
    { plans, id: record?.id ?? null, revision: record?.revision ?? null })).data
}
export async function loadPayments(id: string) {
  return (await axios.get<PaymentRecord>(`/api/workflows/payments/${id}`)).data
}
export async function extractPayment(file: File) {
  const form = new FormData(); form.append('file', file)
  return (await axios.post<PaymentPlan & { missing: string[] }>('/api/workflows/payment-draft', form)).data
}
