import type { ReactNode } from 'react'
import type { Citation } from '../api/types'
import { SourcesAccordion } from './SourcesAccordion'

function keywordPattern(keywords: string[]) {
  const escaped = keywords
    .map((keyword) => keyword.trim())
    .filter((keyword) => keyword.length >= 4)
    .slice(0, 12)
    .map((keyword) => keyword.replace(/[.*+?^$()|[\]{}\\]/g, '\\$&'))
  return escaped.length ? new RegExp('(' + escaped.join('|') + ')', 'gi') : null
}

function renderText(text: string, sources: Citation[], keywords: string[]): ReactNode[] {
  const citationPattern = /(\[\d+\])/g
  const keyword = keywordPattern(keywords)

  return text.split(citationPattern).flatMap((part, index) => {
    const citationMatch = part.match(/^\[(\d+)\]$/)
    if (citationMatch) {
      const source = sources[Number(citationMatch[1]) - 1]
      return (
        <span
          className="inline-citation"
          key={'citation-' + index}
          title={source?.summary || source?.chunk_text || source?.title}
        >
          {part}
        </span>
      )
    }
    if (!keyword) return part
    return part.split(keyword).map((segment, segmentIndex) => {
      const isKeyword = keyword.test(segment)
      keyword.lastIndex = 0
      return isKeyword
        ? <mark key={'keyword-' + index + '-' + segmentIndex}>{segment}</mark>
        : segment
    })
  })
}

export function ResponseRenderer({ content, sources }: { content: string; sources: Citation[] }) {
  const keywords = sources.flatMap((source) => [
    source.title,
    source.section ?? '',
    ...source.breadcrumb,
  ])
  const blocks: ReactNode[] = []
  const codePattern = /\x60\x60\x60([\w+-]*)\n?([\s\S]*?)\x60\x60\x60/g
  let cursor = 0
  let match: RegExpExecArray | null

  while ((match = codePattern.exec(content)) !== null) {
    if (match.index > cursor) {
      blocks.push(
        <p key={'text-' + cursor}>
          {renderText(content.slice(cursor, match.index), sources, keywords)}
        </p>,
      )
    }
    blocks.push(
      <div className="code-block" key={'code-' + match.index}>
        {match[1] && <span>{match[1]}</span>}
        <pre><code>{match[2].trim()}</code></pre>
      </div>,
    )
    cursor = codePattern.lastIndex
  }

  if (cursor < content.length) {
    blocks.push(
      <p key={'text-' + cursor}>
        {renderText(content.slice(cursor), sources, keywords)}
      </p>,
    )
  }

  return (
    <div className="response-renderer">
      {blocks}
      <SourcesAccordion sources={sources} />
    </div>
  )
}
