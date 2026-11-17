import { useEffect, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { indexEvidence, searchEvidence, type EvidenceMatch } from '@/lib/api'
import { PdfViewer } from './PdfViewer'

type Props = {
  files: File[]
}

export function ChecklistEvidenceLocator({ files }: Props) {
  const pdfFiles = files.filter((file) => /\.pdf$/i.test(file.name))
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<EvidenceMatch[]>([])
  const [focusPage, setFocusPage] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const indexed = useRef(new Map<string, string>())

  const selected = pdfFiles[selectedIndex] ?? null

  useEffect(() => {
    setMatches([])
    setFocusPage(null)
    setError('')
  }, [selectedIndex, selected?.name])

  async function locate() {
    if (!selected) {
      setError('请先上传或选择一份 PDF 合同。')
      return
    }
    if (!query.trim()) {
      setError('请输入要定位的原文关键词。')
      return
    }
    setBusy(true)
    setError('')
    try {
      const key = `${selected.name}:${selected.size}:${selected.lastModified}`
      let fileId = indexed.current.get(key)
      if (!fileId) {
        fileId = (await indexEvidence(selected)).file_id
        indexed.current.set(key, fileId)
      }
      const found = await searchEvidence(fileId, query.trim())
      setMatches(found)
      setFocusPage(found[0]?.page ?? null)
    } catch (e) {
      setError(e instanceof Error ? e.message : '定位失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="xl:sticky xl:top-4">
      <CardHeader>
        <CardTitle className="text-base">证据定位</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <select
          className="w-full rounded-md border border-border bg-background px-2 py-2 text-sm"
          value={selectedIndex}
          onChange={(event) => setSelectedIndex(Number(event.target.value))}
          aria-label="选择用于定位的合同"
        >
          {pdfFiles.length ? pdfFiles.map((file, index) => (
            <option key={file.name + file.lastModified} value={index}>{file.name}</option>
          )) : <option value={0}>暂无 PDF 合同</option>}
        </select>
        <div className="flex gap-2">
          <input
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-2 text-sm"
            placeholder="输入原文关键词，例如：手续费"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') void locate() }}
          />
          <Button type="button" variant="secondary" disabled={busy || !selected} onClick={() => void locate()}>
            {busy ? '定位中…' : '定位'}
          </Button>
        </div>
        {error && <p className="text-sm text-red-700" role="alert">{error}</p>}
        {!error && selected && !matches.length && (
          <p className="text-xs text-muted-foreground">定位后会跳到对应页并高亮原文。</p>
        )}
        {matches.length > 0 && (
          <div className="space-y-2">
            <Badge variant="yellow">找到 {matches.length} 处</Badge>
            <ul className="max-h-40 space-y-1 overflow-auto text-xs">
              {matches.map((match, index) => (
                <li key={`${match.page}-${match.top}-${match.x0}-${index}`}>
                  <button type="button" className="text-left underline underline-offset-2"
                    onClick={() => setFocusPage(match.page)}>
                    第 {match.page} 页 · {match.text.slice(0, 80)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <PdfViewer file={selected} matches={matches} focusPage={focusPage} />
      </CardContent>
    </Card>
  )
}
