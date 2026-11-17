import { useEffect, useRef } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { EvidenceMatch } from '@/lib/api'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

interface Props {
  file?: File | null
  matches: EvidenceMatch[]
  focusPage?: number | null
  highlightText?: string
}

const SCALE = 1.4

function normalize(text: string): string {
  return text.replace(/\s+/g, '').toLowerCase()
}

function drawTextHighlight(
  ctx: CanvasRenderingContext2D,
  viewport: pdfjsLib.PageViewport,
  items: Array<{ str?: string; transform?: number[]; width?: number; height?: number }>,
  quote: string,
) {
  const target = normalize(quote).slice(0, 100)
  if (!target) return

  let text = ''
  const spans: Array<{ item: (typeof items)[number]; start: number; end: number }> = []
  for (const item of items) {
    if (!item.str || !item.transform) continue
    const value = normalize(item.str)
    if (!value) continue
    spans.push({ item, start: text.length, end: text.length + value.length })
    text += value
  }

  const start = text.indexOf(target)
  if (start < 0) return
  const end = start + target.length

  ctx.save()
  ctx.fillStyle = 'rgba(255, 213, 79, 0.55)'
  for (const span of spans) {
    if (span.end <= start || span.start >= end) continue
    const tx = pdfjsLib.Util.transform(viewport.transform, span.item.transform)
    const fontHeight = Math.hypot(tx[2], tx[3]) || (span.item.height ?? 12) * viewport.scale
    const width = (span.item.width ?? 0) * viewport.scale
    ctx.fillRect(tx[4], tx[5] - fontHeight, width, fontHeight * 1.25)
  }
  ctx.restore()
}

export function PdfViewer({ file, matches, focusPage, highlightText }: Props) {
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
        const wrapper = document.createElement('div')
        wrapper.dataset.page = String(pageNum)
        wrapper.className = 'relative'

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

        if (highlightText && (!focusPage || focusPage === pageNum)) {
          const textContent = await page.getTextContent()
          drawTextHighlight(ctx, viewport, textContent.items as any[], highlightText)
        }

        if (cancelled) return
        wrapper.appendChild(canvas)
        c.appendChild(wrapper)
      }

      if (focusPage) {
        const target = c.querySelector(`[data-page="${focusPage}"]`)
        target?.scrollIntoView({ block: 'start' })
      }
    }

    const c = container
    const f = file
    render(c, f).catch(console.error)
    return () => {
      cancelled = true
    }
  }, [file, matches, focusPage, highlightText])

  return <div ref={containerRef} className="w-full max-h-[78vh] overflow-auto" />
}
