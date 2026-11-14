import axios from 'axios'

export interface EvidenceMatch {
  page: number
  x0: number
  top: number
  x1: number
  bottom: number
  text: string
}

export type VamRole = 'tenant' | 'landlord' | 'company' | 'investor' | 'other'
export type VamObjective = 'cash' | 'liability' | 'timing' | 'equity'
export type VamTemplate = 'repurchase' | 'lease_exit' | 'qualitative'
export type VamTrigger = 'met' | 'not_met' | 'unknown'
export type VamWeights = Record<'risk_score' | 'feasibility_score' | 'loss_score', number>

export interface VamEvidenceInput {
  file_id: string
  filename: string
  page: number
  quote: string
}

export interface VamAction {
  label: string
  terms: string
  parameters: Record<string, string | number | boolean | null>
}

export interface VamStudy {
  role: VamRole | null
  objective: VamObjective | null
  template: VamTemplate
  actions: VamAction[]
  experimental_scoring: boolean
  weights: VamWeights
}

export interface VamEvaluation {
  leaf_id: string
  risk_score: number | null
  feasibility_score: number | null
  loss_score: number | null
  confidence: number | null
  evidence: string
  scorer_model?: string | null
  total_score: number | null
  status: 'valid' | 'missing' | 'invalid' | 'error' | 'disabled'
  invalid_fields: string[]
}

export interface VamConsequence {
  action_id: string
  amount: number | null
  payment_days: number | null
  cap: number | null
  missing: string[]
  formula: string
  effect: string
}

export interface VamScenarioComparison {
  leaf_id: string
  path: string[]
  branch: string
  trigger: VamTrigger
  cells: VamConsequence[]
  preferred_action_ids: string[]
  reason: string
}

export interface VamTreeNode {
  id: string
  branch: string
  premise: string
  events: string[]
  risks: string[]
  upsides: string[]
  key_variables: string[]
  trigger: VamTrigger
  trigger_override?: VamTrigger
  evidence_ids: string[]
  children: VamTreeNode[]
  evaluation?: VamEvaluation
  _risk?: number | null
}

export interface VamResult {
  run_id: string
  query: string
  scenario: string
  assumptions: string[]
  uncertainties: string[]
  warnings: string[]
  tree: {
    scenario: string
    assumptions: string[]
    uncertainties: string[]
    trigger_excerpt?: { quote: string; evidence_id: string | null } | null
    branches: VamTreeNode[]
  }
  study: Omit<VamStudy, 'actions'> & {
    actions: (VamAction & { id: string })[]
    evidence: (Omit<VamEvidenceInput, 'file_id'> & { id: string })[]
  }
  comparison: {
    template: VamTemplate
    direction: 'pay' | 'receive' | null
    scenarios: VamScenarioComparison[]
    max_amounts: Record<string, number | null>
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

export async function runVam(query: string, study: VamStudy, evidence: VamEvidenceInput[]) {
  const res = await axios.post<VamResult>('/api/vam/run', { query, ...study, evidence })
  return res.data
}

export async function deepenVam(result: VamResult, leafId: string) {
  const res = await axios.post<VamResult>('/api/vam/deepen', { result: { run_id: result.run_id }, leaf_id: leafId })
  return res.data
}

export async function exportVam(result: VamResult) {
  const res = await axios.post<{ markdown: string }>('/api/vam/export', { result: { run_id: result.run_id } })
  return res.data.markdown
}

export async function compareVam(result: VamResult, actions: VamAction[], weights: VamWeights,
  triggers: Record<string, VamTrigger> = {}) {
  const res = await axios.post<VamResult>('/api/vam/compare', { run_id: result.run_id, actions, weights, triggers })
  return res.data
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
