import { useState } from 'react'
import { CashflowPage } from './components/CashflowPage'
import { ClauseComparePage } from './components/ClauseComparePage'
import { ContractPage } from './components/ContractPage'
import { VamPage } from './components/VamPage'

type Tab = 'contract' | 'compare' | 'vam' | 'cashflow'

const tabs: { key: Tab; label: string }[] = [
  { key: 'contract', label: '合同核验' },
  { key: 'compare', label: '宣传 vs 合同' },
  { key: 'vam', label: '对赌协议推演' },
  { key: 'cashflow', label: '资金流' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('contract')

  return (
    <div className="min-h-screen">
      <header className="border-b border-border bg-background">
        <div className="mx-auto flex max-w-[1700px] items-center justify-between px-4 py-4">
          <div className="text-lg font-semibold">签之前 · 合同核验与推演</div>
          <nav className="flex gap-1">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
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
        {tab === 'contract' && <ContractPage onOpenVam={() => setTab('vam')} />}
        {tab === 'compare' && <ClauseComparePage />}
        {tab === 'vam' && <VamPage />}
        {tab === 'cashflow' && <CashflowPage />}
      </main>
    </div>
  )
}
