import type { Citation } from '../api/types'

function safeHttpUrl(value: string | null) {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null
  } catch {
    return null
  }
}

export function SourcesAccordion({ sources }: { sources: Citation[] }) {
  if (!sources.length) return null
  return (
    <details className="sources-accordion">
      <summary>{sources.length} {sources.length === 1 ? 'SOURCE' : 'SOURCES'}</summary>
      <div className="source-list">
        {sources.map((source, index) => {
          const href = safeHttpUrl(source.source_url)
          const location = [
            source.page_number === null ? null : `PAGE ${source.page_number}`,
            source.section,
          ].filter(Boolean).join(' · ')
          const normalizedChunk = source.chunk_text.replace(/\s+/g, ' ').trim()
          const excerpt = normalizedChunk.length > 220
            ? `${normalizedChunk.slice(0, 217).trimEnd()}...`
            : normalizedChunk
          const confidence = source.relevance ?? source.score
          return (
            <article className="source-card" key={`${source.document_id}-${index}`}>
              <div className="source-heading">
                <strong>{index + 1}. {source.title}</strong>
                {confidence !== null && <span>{Math.round(confidence * 100)}%</span>}
              </div>
              {location && <small>{location}</small>}
              <p>{excerpt}</p>
              {href ? (
                <a href={href} target="_blank" rel="noreferrer">OPEN SOURCE ↗</a>
              ) : source.file_path ? (
                <code>{source.file_path}</code>
              ) : null}
            </article>
          )
        })}
      </div>
    </details>
  )
}
