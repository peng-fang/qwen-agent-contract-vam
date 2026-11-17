import { useState } from 'react'
import { ClauseComparePage } from './components/ClauseComparePage'
import { ContractPage } from './components/ContractPage'
import { ChecklistPage } from './components/ChecklistPage'
import type { VamEvidenceInput } from './lib/api'

type Tab = 'contract' | 'compare' | 'checklist'

const tabs: { key: Tab; label: string }[] = [
  { key: 'contract', label: '合同核验' },
  { key: 'compare', label: '宣传 vs 合同' },
  { key: 'checklist', label: '签约前必问清单' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('contract')
  const [files, setFiles] = useState<File[]>([])
  const [checklistEvidence, setChecklistEvidence] = useState<VamEvidenceInput[]>([])
  const [checklistVersion, setChecklistVersion] = useState(0)

  function addChecklist(evidence: VamEvidenceInput | VamEvidenceInput[]) {
    const incoming = Array.isArray(evidence) ? evidence : [evidence]
    setChecklistEvidence((items) => {
      const merged = [...items]
      for (const entry of incoming) {
        if (!merged.some((item) => item.file_id === entry.file_id && item.page === entry.page && item.quote === entry.quote)) {
          merged.push(entry)
        }
      }
      return merged.slice(-30)
    })
  }

  function removeChecklist(evidence: VamEvidenceInput) {
    setChecklistEvidence((items) => items.filter((item) =>
      !(item.file_id === evidence.file_id && item.page === evidence.page && item.quote === evidence.quote)))
  }

  function removeFile(file: File) {
    setFiles((items) => items.filter((item) => !(item.name === file.name && item.lastModified === file.lastModified)))
  }

  function openChecklist(evidence?: VamEvidenceInput | VamEvidenceInput[]) {
    if (evidence) {
      addChecklist(evidence)
      setChecklistVersion((version) => version + 1)
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
        <div hidden={tab !== 'contract'}>
          <ContractPage
            files={files}
            onFilesChange={setFiles}
            checklistEvidence={checklistEvidence}
            onAddChecklist={addChecklist}
            onRemoveChecklist={removeChecklist}
            onOpenChecklist={openChecklist}
          />
        </div>
        {tab === 'compare' && (
          <ClauseComparePage
            sharedFiles={files}
            onFilesChange={setFiles}
            checklistEvidence={checklistEvidence}
            onAddChecklist={addChecklist}
            onRemoveChecklist={removeChecklist}
          />
        )}
        <div hidden={tab !== 'checklist'}>
          <ChecklistPage
            key={checklistVersion}
            evidence={checklistEvidence}
            onRemoveEvidence={(index) => {
              setChecklistEvidence((items) => items.filter((_, i) => i !== index))
            }}
            sharedFiles={files}
            onFilesChange={setFiles}
            onRemoveFile={removeFile}
          />
        </div>
      </main>
    </div>
  )
}
