import { useEffect, useRef } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { EvidenceMatch } from '@/lib/api'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

interface Props {
  file?: File | null
  matches: EvidenceMatch[]
}

const SCALE = 1.4

export function PdfViewer({ file, matches }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    const container = containerRef.current
    if (!container || !file) return

    async function render(c: HTMLDivElement, f: File) {
      c.innerHTML = ''
      const data = await f.arrayBuffer()
      const pdf = await pdfjsLib.getDocument({ data }).promise

      for (let pageNum = 1; pageNum <= pdf.numPages; pageNum += 1) {
        const page = await pdf.getPage(pageNum)
        const viewport = page.getViewport({ scale: SCALE })
        const canvas = document.createElement('canvas')
        canvas.width = viewport.width
        canvas.height = viewport.height
        canvas.className = 'block mx-auto my-2 rounded shadow'
        const ctx = canvas.getContext('2d')
        if (!ctx) continue
        await page.render({ canvas, canvasContext: ctx, viewport }).promise

        const pageMatches = matches.filter((m) => m.page === pageNum)
        for (const m of pageMatches) {
          ctx.fillStyle = 'rgba(255,235,59,0.45)'
          ctx.fillRect(
            m.x0 * SCALE,
            m.top * SCALE,
            (m.x1 - m.x0) * SCALE,
            (m.bottom - m.top) * SCALE,
          )
        }

        if (cancelled) return
        c.appendChild(canvas)
      }
    }

    const c = container
    const f = file
    render(c, f).catch(console.error)
    return () => {
      cancelled = true
    }
  }, [file, matches])

  return <div ref={containerRef} className="w-full max-h-[70vh] overflow-auto" />
}
