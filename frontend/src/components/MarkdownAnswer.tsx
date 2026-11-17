import type { ReactNode } from 'react'

type Block =
  | { type: 'heading'; level: number; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'list'; items: string[] }
  | { type: 'table'; headers: string[]; rows: string[][] }

function cells(line: string): string[] {
  const trimmed = line.trim()
  const body = trimmed.startsWith('|') ? trimmed.slice(1) : trimmed
  return (body.endsWith('|') ? body.slice(0, -1) : body)
    .split('|')
    .map((cell) => cell.trim())
}

function isSeparator(line: string): boolean {
  const values = cells(line)
  return values.length > 0 && values.every((cell) => /^:?-{2,}:?$/.test(cell))
}

function isTableStart(lines: string[], index: number): boolean {
  return lines[index].includes('|') && index + 1 < lines.length && isSeparator(lines[index + 1])
}

function parse(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n')
  const blocks: Block[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }

    if (isTableStart(lines, index)) {
      const headers = cells(line)
      const rows: string[][] = []
      index += 2
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
        rows.push(cells(lines[index]))
        index += 1
      }
      blocks.push({ type: 'table', headers, rows })
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2] })
      index += 1
      continue
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ''))
        index += 1
      }
      blocks.push({ type: 'list', items })
      continue
    }

    if (/^\s*\d+[.、]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*\d+[.、]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+[.、]\s+/, ''))
        index += 1
      }
      blocks.push({ type: 'list', items })
      continue
    }

    const paragraph = [line]
    index += 1
    while (
      index < lines.length
      && lines[index].trim()
      && !isTableStart(lines, index)
      && !/^#{1,6}\s+/.test(lines[index])
      && !/^\s*[-*]\s+/.test(lines[index])
      && !/^\s*\d+[.、]\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push({ type: 'paragraph', text: paragraph.join('\n') })
  }

  return blocks
}

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={index}>{part.slice(2, -2)}</strong>
    }
    return part
  })
}

export function MarkdownAnswer({ text }: { text: string }) {
  const blocks = parse(text)
  return (
    <div className="space-y-3 text-sm leading-6">
      {blocks.map((block, blockIndex) => {
        if (block.type === 'table') {
          return (
            <div key={blockIndex} className="overflow-x-auto rounded-lg border">
              <table className="min-w-full border-collapse text-left text-sm">
                <thead className="bg-muted/70">
                  <tr>
                    {block.headers.map((header, index) => (
                      <th key={index} className="whitespace-nowrap border-b px-3 py-2 font-medium">
                        {inline(header)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex} className="border-b last:border-0">
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex} className="min-w-28 border-r px-3 py-2 align-top last:border-r-0">
                          {inline(cell)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        if (block.type === 'heading') {
          return <h3 key={blockIndex} className="pt-1 text-base font-semibold">{inline(block.text)}</h3>
        }
        if (block.type === 'list') {
          return (
            <ul key={blockIndex} className="list-disc space-y-1 pl-5">
              {block.items.map((item, index) => <li key={index}>{inline(item)}</li>)}
            </ul>
          )
        }
        return <p key={blockIndex} className="whitespace-pre-wrap break-words">{inline(block.text)}</p>
      })}
    </div>
  )
}
