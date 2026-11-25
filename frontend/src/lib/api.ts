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
  const res = await axios.post<{
    question: string
    answer: string
    files: string[]
    amount_checks: (AmountCheck & { clause_type: string; clause_label: string })[]
    amount_notice: string
  }>('/api/contract/analyze', form)
  return res.data
}

export async function analyzeContractStream(
  question: string,
  files: File[],
  onChunk: (text: string) => void,
  signal?: AbortSignal,
) {
  const form = new FormData()
  form.append('question', question)
  files.forEach((f) => form.append('files', f))

  const response = await fetch('/api/contract/analyze/stream', {
    method: 'POST',
    body: form,
    signal,
  })
  if (!response.ok || !response.body) {
    const raw = await response.text().catch(() => '')
    let detail = raw
    try {
      detail = JSON.parse(raw).detail ?? raw
    } catch {
      // Keep the raw response when the server did not return JSON.
    }
    throw new Error(detail || `请求失败（${response.status}）`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let answer = ''
  let resultFiles: string[] = []
  let amountChecks: (AmountCheck & { clause_type: string; clause_label: string })[] = []
  let amountNotice = ''
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
        text?: string
        detail?: string
        files?: string[]
        amount_checks?: (AmountCheck & { clause_type: string; clause_label: string })[]
        amount_notice?: string
      }
      if (payload.type === 'chunk' && typeof payload.text === 'string') {
        answer = payload.text
        onChunk(answer)
      } else if (payload.type === 'done') {
        resultFiles = payload.files ?? []
        amountChecks = payload.amount_checks ?? []
        amountNotice = payload.amount_notice ?? ''
      } else if (payload.type === 'error') {
        throw new Error(payload.detail || '核验失败')
      }
    }
  }
  if (!answer) throw new Error('核验流意外结束，请重试。')
  return {
    answer,
    files: resultFiles,
    amount_checks: amountChecks,
    amount_notice: amountNotice,
  }
}

export type RentalRegion = 'mainland' | 'hongkong'
export type RentalContractType =
  | 'auto'
  | 'rental'
  | 'consumer'
  | 'procurement'
  | 'labor'
  | 'loan'
  | 'ecommerce'
  | 'franchise'
  | 'dispute'
  | 'other'

export interface RentalLegalBasis {
  article_id: string
  article: string
  title: string
  summary: string
  source: string
  source_url: string
  jurisdiction: RentalRegion
  contract_types: string[]
  source_type?: 'local' | 'official_web' | 'unknown'
  verified?: boolean
  retrieved_at?: string | null
  note: string
  matched_keywords: string[]
}

export interface RentalRisk {
  risk_id: string
  title: string
  risk_type: string
  severity: 'high' | 'medium' | 'low'
  clause_ids: string[]
  page: number | null
  quote: string
  explanation: string
  suggestion: string
  legal_basis: RentalLegalBasis[]
  confidence: number
  evidence_verified: boolean
  status: 'supported' | 'needs_review' | 'rejected'
  judge_reason: string
  source: string
}

export interface RentalReviewResult {
  report_id?: string
  filename: string
  file_id?: string | null
  file_type: string
  region: RentalRegion
  region_label: string
  contract_type: Exclude<RentalContractType, 'auto'>
  contract_type_label: string
  contract_type_requested: RentalContractType
  classification: {
    contract_type: Exclude<RentalContractType, 'auto'>
    confidence: number
    legal_domains: string[]
    jurisdiction_hint: string
    reason: string
    source: string
    known_type?: boolean
  }
  page_count: number
  clause_count: number
  facts: Record<string, unknown>
  risks: RentalRisk[]
  summary: {
    risk_score: number
    risk_level: 'high' | 'medium' | 'low'
    risk_level_label: string
    total_risks: number
    high_count: number
    medium_count: number
    needs_review_count: number
  }
  agent_trace: { agent: string; status: string; detail: string }[]
  warnings: string[]
  disclaimer: string
  cache_hit?: boolean
}

export async function reviewRentalContract(
  file: File,
  contractType: RentalContractType = 'rental',
  region: RentalRegion = 'mainland',
  useLlm = true,
) {
  const form = new FormData()
  form.append('file', file)
  form.append('contract_type', contractType)
  form.append('region', region)
  form.append('use_llm', String(useLlm))
  const res = await axios.post<RentalReviewResult>('/api/contract/rental-review', form, {
    timeout: 300000,
  })
  return res.data
}

export interface RentalReviewProgress {
  stage: string
  status: 'running' | 'done' | 'warning'
  detail: string
}

export async function reviewRentalContractStream(
  file: File,
  contractType: RentalContractType = 'rental',
  region: RentalRegion = 'mainland',
  useLlm = true,
  onProgress?: (event: RentalReviewProgress) => void,
  signal?: AbortSignal,
  onPartial?: (risks: RentalRisk[]) => void,
): Promise<RentalReviewResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('contract_type', contractType)
  form.append('region', region)
  form.append('use_llm', String(useLlm))

  const response = await fetch('/api/contract/rental-review/stream', {
    method: 'POST',
    body: form,
    signal,
  })
  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => '')
    throw new Error(text || `请求失败（${response.status}）`)
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
      const dataLine = block
        .split('\n')
        .find((line) => line.startsWith('data:'))
      if (!dataLine) continue
      const payload = JSON.parse(dataLine.slice(5).trim()) as {
        type: string
        stage?: string
        status?: 'running' | 'done' | 'warning'
        detail?: string
        result?: RentalReviewResult
        risks?: RentalRisk[]
      }
      if (payload.type === 'progress' && payload.stage && payload.status) {
        onProgress?.({
          stage: payload.stage,
          status: payload.status,
          detail: payload.detail ?? '',
        })
      } else if (payload.type === 'partial' && Array.isArray(payload.risks)) {
        onPartial?.(payload.risks)
      } else if (payload.type === 'result' && payload.result) {
        return payload.result
      } else if (payload.type === 'error') {
        throw new Error(payload.detail || '审查失败')
      }
    }
  }
  throw new Error('审查流意外结束，请重试。')
}

export async function searchEvidence(filename: string, query: string) {
  const res = await axios.post<{ matches: EvidenceMatch[] }>('/api/evidence/search', {
    filename,
    query,
  })
  return res.data.matches
}

export async function indexEvidence(file: File) {
  const body = new FormData()
  body.append('file', file)
  const res = await axios.post<{ file_id: string; filename: string }>('/api/evidence/index', body)
  return res.data
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

export type ClauseVerdictGroup = 'consistent' | 'conflict' | 'insufficient'

export interface ClauseEvidence {
  evidence_id: string
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

export type AmountStatus =
  | 'applicable'
  | 'conditional'
  | 'insufficient'
  | 'not_applicable'
  | 'no_amount'

export interface AmountCondition {
  condition: string
  met: boolean | null
  evidence_id: string
  quote: string
}

export interface AmountScenario {
  label: string
  condition: string
  amount: number | null
  formula: string
  applicable: boolean | null
  missing: string[]
  evidence_ids: string[]
}

export interface AmountCheck {
  status: AmountStatus
  status_label: string
  reason?: string
  basis: AmountCondition[]
  scenarios: AmountScenario[]
  missing: string[]
  method: string
  note?: string
}

export interface ClauseMatch {
  clause_type: ClauseType
  clause_label: string
  verdict: ClauseVerdict
  verdict_label: string
  verdict_group: ClauseVerdictGroup
  verdict_group_label: string
  reasons: string[]
  promo: ClauseSide | null
  contract: ClauseSide | null
  compared: Record<string, unknown>
  amount?: AmountCheck | null
}

export interface EvidenceReviewFailure {
  evidence_id: string
  clause_type: string
  clause_label: string
  page: number
  filename: string
  problems: string[]
}

export interface EvidenceReview {
  method: string
  checked: number
  passed: number
  failed: number
  failures: EvidenceReviewFailure[]
  note: string
}

export interface RiskRedline {
  clause_type: string
  clause_label: string
  severity: 'high' | 'medium' | 'low'
  reason: string
  evidence_ids: string[]
}

export interface RiskAssessment {
  score: number
  level: 'high' | 'medium' | 'low'
  level_label: string
  redlines: RiskRedline[]
  factors: string[]
  method: string
  note: string
}

export interface RelatedEvidenceExcerpt {
  evidence_id: string
  filename: string
  page: number
  char_start: number
  char_end: number
  quote: string
  relation: 'qualifier' | 'reference'
  reference_path?: { article: string; from_evidence_id: string; to_evidence_id: string }[]
}

export interface RelatedEvidence {
  related: RelatedEvidenceExcerpt[]
  extra_quote_chars: number
  omitted: number
}

export interface ResolvedEvidence {
  evidence_id: string
  document_id: string
  filename: string
  role: string
  page: number
  char_start: number
  char_end: number
  quote: string
  context: string
  verified: boolean
  related_evidence?: RelatedEvidence
}

export interface VersionDiffRow {
  clause_type: ClauseType
  clause_label: string
  status: 'added' | 'removed' | 'changed' | 'unchanged'
  changes: { field: string; old: unknown; new: unknown }[]
  old: { clause_count: number; evidences: ClauseEvidence[] }
  new: { clause_count: number; evidences: ClauseEvidence[] }
}

export interface VersionCompareResult {
  old_document: { document_id: string; filename: string }
  new_document: { document_id: string; filename: string }
  summary: { added: number; removed: number; changed: number; unchanged: number }
  rows: VersionDiffRow[]
  method: string
}

export interface ClauseExtractionResult {
  task_id?: string
  task_revision?: number
  documents: {
    document_id: string
    file_id?: string
    filename: string
    role: string
    pages: { page: number; text: string }[]
  }[]
  clauses: ExtractedClause[]
  matches: ClauseMatch[]
  extractor: string
  warnings: string[]
  evidence_review: EvidenceReview
  risk: RiskAssessment
}

export async function extractClauses(files: File[], roles?: string[]) {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  if (roles?.length) form.append('roles', roles.join(','))
  const res = await axios.post<ClauseExtractionResult>('/api/contract/clauses', form)
  return res.data
}

export async function resolveEvidence(evidenceId: string, includeRelated = false) {
  const res = await axios.get<ResolvedEvidence>(
    `/api/contract/evidence/${encodeURIComponent(evidenceId)}`,
    { params: { include_related: includeRelated } },
  )
  return res.data
}

export async function compareContractVersions(oldFile: File, newFile: File) {
  const form = new FormData()
  form.append('old_file', oldFile)
  form.append('new_file', newFile)
  const res = await axios.post<VersionCompareResult>('/api/contract/versions', form)
  return res.data
}
