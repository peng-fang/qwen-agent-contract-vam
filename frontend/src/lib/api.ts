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
