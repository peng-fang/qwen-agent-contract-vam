import { useState } from 'react'
import { CashflowPage } from './components/CashflowPage'
import { ClauseComparePage } from './components/ClauseComparePage'
import { ContractPage } from './components/ContractPage'
import { ChecklistPage } from './components/ChecklistPage'
import type { VamEvidenceInput } from './lib/api'

type Tab = 'contract' | 'compare' | 'checklist' | 'cashflow'

const tabs: { key: Tab; label: string }[] = [
  { key: 'contract', label: '合同核验' },
  { key: 'compare', label: '宣传 vs 合同' },
  { key: 'checklist', label: '签约前必问清单' },
  { key: 'cashflow', label: '资金流' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('contract')
  const [checklistEvidence, setChecklistEvidence] = useState<VamEvidenceInput[]>([])
  const [checklistVersion, setChecklistVersion] = useState(0)

  function openChecklist(evidence?: VamEvidenceInput) {
    if (evidence) {
      setChecklistVersion((version) => version + 1)
      setChecklistEvidence((items) => [
        ...items.filter((item) => !(item.file_id === evidence.file_id && item.page === evidence.page && item.quote === evidence.quote)),
        evidence,
      ].slice(-6))
    }
    setTab('checklist')
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-border bg-background">
        <div className="mx-auto flex max-w-[1700px] flex-wrap items-center justify-between gap-2 px-4 py-4">
          <div className="text-lg font-semibold">签之前 · 合同核验</div>
          <nav className="flex flex-wrap gap-1">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                aria-current={tab === t.key ? 'page' : undefined}
                className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                  tab === t.key
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-accent'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1700px] px-4 py-6">
        <div hidden={tab !== 'contract'}><ContractPage onOpenChecklist={openChecklist} /></div>
        {tab === 'compare' && <ClauseComparePage />}
        <div hidden={tab !== 'checklist'}><ChecklistPage key={checklistVersion} evidence={checklistEvidence} onRemoveEvidence={(index) => {
          setChecklistEvidence((items) => items.filter((_, i) => i !== index))
        }} /></div>
        {tab === 'cashflow' && <CashflowPage />}
      </main>
    </div>
  )
}
