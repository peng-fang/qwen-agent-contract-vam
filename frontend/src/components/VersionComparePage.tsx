import { useState } from 'react'
import axios from 'axios'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  compareContractVersions,
  type VersionCompareResult,
  type VersionDiffRow,
} from '@/lib/api'

const STATUS_LABEL: Record<VersionDiffRow['status'], string> = {
  added: '新增',
  removed: '删除',
  changed: '变更',
  unchanged: '未变',
}

const STATUS_VARIANT: Record<VersionDiffRow['status'], 'red' | 'yellow' | 'green' | 'secondary'> = {
  added: 'yellow',
  removed: 'red',
  changed: 'yellow',
  unchanged: 'green',
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.length ? JSON.stringify(value) : '—'
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    return entries.length ? JSON.stringify(value) : '—'
  }
  return String(value)
}

function errorText(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: string } | undefined)?.detail
    if (detail) return detail
  }
  return error instanceof Error ? error.message : '请求失败'
}

export function VersionComparePage() {
  const [oldFile, setOldFile] = useState<File | null>(null)
  const [newFile, setNewFile] = useState<File | null>(null)
  const [result, setResult] = useState<VersionCompareResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function run() {
    setError('')
    if (!oldFile || !newFile) {
      setError('请同时选择旧合同和新合同。')
      return
    }
    setLoading(true)
    try {
      setResult(await compareContractVersions(oldFile, newFile))
    } catch (e) {
      setResult(null)
      setError(`版本对比失败：${errorText(e)}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <Card className="border-0 bg-gradient-to-br from-slate-50 to-emerald-50 shadow-sm">
        <CardContent className="p-6">
          <h1 className="text-2xl font-bold tracking-tight">合同版本对比</h1>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            上传旧版与新版合同，按五类条款比较金额、比例、期限、通知期和条件；
            变化由确定性字段比对得出，每条变化都可回查原文。
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>选择两份合同</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">旧合同</span>
              <input
                type="file"
                accept=".pdf,.txt,.md"
                className="block w-full text-sm text-muted-foreground"
                onChange={(e) => setOldFile(e.target.files?.[0] ?? null)}
              />
              <span className="block truncate text-xs text-muted-foreground">
                {oldFile ? oldFile.name : '例如 demo_data/contract_gym.pdf'}
              </span>
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">新合同</span>
              <input
                type="file"
                accept=".pdf,.txt,.md"
                className="block w-full text-sm text-muted-foreground"
                onChange={(e) => setNewFile(e.target.files?.[0] ?? null)}
              />
              <span className="block truncate text-xs text-muted-foreground">
                {newFile ? newFile.name : '例如 demo_data/contract_gym.pdf'}
              </span>
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={run} disabled={loading}>
              {loading ? '对比中…' : '开始对比'}
            </Button>
            {result && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge variant="yellow">新增 {result.summary.added}</Badge>
                <Badge variant="red">删除 {result.summary.removed}</Badge>
                <Badge variant="yellow">变更 {result.summary.changed}</Badge>
                <Badge variant="green">未变 {result.summary.unchanged}</Badge>
              </div>
            )}
          </div>

          {error && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {error}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>逐类条款变化</CardTitle>
        </CardHeader>
        <CardContent>
          {!result && !error && (
            <div className="rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
              尚未开始对比。选择旧版与新版合同后点击「开始对比」。
            </div>
          )}
          {result && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] border-collapse text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="w-36 p-3 font-medium">条款</th>
                    <th className="w-24 p-3 font-medium">状态</th>
                    <th className="p-3 font-medium">字段变化</th>
                    <th className="w-56 p-3 font-medium">旧合同证据</th>
                    <th className="w-56 p-3 font-medium">新合同证据</th>
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row) => (
                    <tr key={row.clause_type}>
                      <td className="border-t border-border p-3 align-top font-medium">
                        {row.clause_label}
                      </td>
                      <td className="border-t border-border p-3 align-top">
                        <Badge variant={STATUS_VARIANT[row.status]}>
                          {STATUS_LABEL[row.status]}
                        </Badge>
                      </td>
                      <td className="border-t border-border p-3 align-top">
                        {row.changes.length ? (
                          <ul className="space-y-1 text-xs">
                            {row.changes.map((change) => (
                              <li key={change.field}>
                                <span className="font-mono text-muted-foreground">
                                  {change.field}
                                </span>
                                ：{formatValue(change.old)} → {formatValue(change.new)}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <span className="text-sm text-muted-foreground">无字段变化</span>
                        )}
                      </td>
                      <td className="border-t border-border p-3 align-top">
                        {row.old.evidences.length ? (
                          <ul className="space-y-1 text-xs text-muted-foreground">
                            {row.old.evidences.slice(0, 2).map((item) => (
                              <li key={item.evidence_id}>
                                <div>第 {item.page} 页 · {item.quote.slice(0, 30)}</div>
                                <div className="break-all font-mono text-[11px]">
                                  {item.evidence_id}
                                </div>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <span className="text-sm text-muted-foreground">无</span>
                        )}
                      </td>
                      <td className="border-t border-border p-3 align-top">
                        {row.new.evidences.length ? (
                          <ul className="space-y-1 text-xs text-muted-foreground">
                            {row.new.evidences.slice(0, 2).map((item) => (
                              <li key={item.evidence_id}>
                                <div>第 {item.page} 页 · {item.quote.slice(0, 30)}</div>
                                <div className="break-all font-mono text-[11px]">
                                  {item.evidence_id}
                                </div>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <span className="text-sm text-muted-foreground">无</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
