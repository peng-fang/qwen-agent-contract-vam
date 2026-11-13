import axios from 'axios'

export interface EvidenceMatch {
  page: number
  x0: number
  top: number
  x1: number
  bottom: number
  text: string
}

export interface VamRanked {
  path: string[]
  branch: string
  leaf_id: string
  benefit: number
  risk: number
  probability: number
  cost: number
  opportunity_cost: number
  total_score: number
  recommendation: string
  reasons: string[]
}

export interface VamTreeNode {
  id: string
  branch: string
  premise: string
  events: string[]
  risks: string[]
  upsides: string[]
  key_variables: string[]
  children: VamTreeNode[]
  evaluation?: {
    leaf_id: string
    benefit: number
    risk: number
    probability: number
    cost: number
    opportunity_cost: number
    total_score: number
    recommendation: string
    reasons: string[]
  }
  _risk?: number
}

export interface VamResult {
  query: string
  scenario: string
  assumptions: string[]
  uncertainties: string[]
  tree: {
    scenario: string
    assumptions: string[]
    uncertainties: string[]
    branches: VamTreeNode[]
  }
  ranked: VamRanked[]
  best: {
    path: string[]
    branch: string
    leaf_id: string
    total_score: number
  }
}

export async function analyzeContract(question: string, files: File[]) {
  const form = new FormData()
  form.append('question', question)
  files.forEach((f) => form.append('files', f))
  const res = await axios.post<{ question: string; answer: string; files: string[] }>(
    '/api/contract/analyze',
    form,
  )
  return res.data
}

export async function searchEvidence(filename: string, query: string) {
  const res = await axios.post<{ matches: EvidenceMatch[] }>('/api/evidence/search', {
    filename,
    query,
  })
  return res.data.matches
}

export async function runVam(query: string) {
  const res = await axios.post<VamResult>('/api/vam/run', { query })
  return res.data
}

export async function deepenVam(result: VamResult, leafId: string) {
  const res = await axios.post<VamResult>('/api/vam/deepen', { result, leaf_id: leafId })
  return res.data
}

export async function exportVam(result: VamResult) {
  const res = await axios.post<{ markdown: string }>('/api/vam/export', { result })
  return res.data.markdown
}

export type ClauseType =
  | 'refund'
  | 'penalty'
  | 'auto_renewal'
  | 'service_term'
  | 'extra_fee'

export type ClauseVerdict =
  | 'consistent'
  | 'conflict'
  | 'missing_in_contract'
  | 'missing_in_promo'
  | 'missing_both'
  | 'unclear'

export interface ClauseEvidence {
  document_id: string
  filename: string
  role: string
  page: number
  chunk_id: string
  char_start: number
  char_end: number
  quote: string
}

export interface ClauseFields {
  amounts: number[]
  rates: number[]
  per_unit_amounts: { amount: number; unit: string }[]
  durations: { value: number; unit: string }[]
  dates: string[]
  notice_days: number | null
  conditions: string[]
  flags: Record<string, boolean>
  clause_ref: string
}

export interface ExtractedClause {
  clause_type: ClauseType
  clause_label: string
  evidence: ClauseEvidence
  fields: ClauseFields
  confidence: number
  extractor: string
}

export interface ClauseSide {
  clause_refs: string[]
  fields: ClauseFields
  evidences: ClauseEvidence[]
}

export interface ClauseMatch {
  clause_type: ClauseType
  clause_label: string
  verdict: ClauseVerdict
  verdict_label: string
  reasons: string[]
  promo: ClauseSide | null
  contract: ClauseSide | null
  compared: Record<string, unknown>
}

export interface ClauseExtractionResult {
  documents: {
    document_id: string
    filename: string
    role: string
    pages: { page: number; text: string }[]
  }[]
  clauses: ExtractedClause[]
  matches: ClauseMatch[]
  extractor: string
  warnings: string[]
}

export async function extractClauses(files: File[], roles?: string[]) {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  if (roles?.length) form.append('roles', roles.join(','))
  const res = await axios.post<ClauseExtractionResult>('/api/contract/clauses', form)
  return res.data
}
