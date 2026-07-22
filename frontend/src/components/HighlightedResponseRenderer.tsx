import { useState } from 'react'
import type { ReactNode } from 'react'
import { Check, Copy } from 'lucide-react'
import { Highlight, themes } from 'prism-react-renderer'
import type { Language } from 'prism-react-renderer'
import type { Citation } from '../api/types'
import { Button } from './ui/button'
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

const languageAliases: Record<string, Language> = {
  cs: 'csharp',
  html: 'markup',
  js: 'javascript',
  md: 'markdown',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  ts: 'typescript',
  yml: 'yaml',
}

function languageFor(value: string): Language {
  const normalized = value.trim().toLowerCase()
  return languageAliases[normalized] ?? (normalized || 'text') as Language
}

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  textarea.remove()
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false)
  const normalizedCode = code.replace(/^\n|\n$/g, '')

  const handleCopy = async () => {
    try {
      await copyText(normalizedCode)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="code-block group/code">
      <div className="flex items-center justify-between border-b border-white/10 bg-[#181818] px-3 py-2">
        <span className="font-mono text-[0.7rem] uppercase tracking-wider text-zinc-400">
          {language || 'code'}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => void handleCopy()}
          className="h-7 gap-1.5 px-2 text-xs text-zinc-300 hover:bg-white/10 hover:text-white"
          aria-label={copied ? 'Code copied' : 'Copy code'}
        >
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <Highlight theme={themes.vsDark} code={normalizedCode} language={languageFor(language)}>
        {({ className, style, tokens, getLineProps, getTokenProps }) => (
          <pre className={className} style={{ ...style, background: '#1e1e1e' }}>
            <code>
              {tokens.map((line, lineIndex) => (
                <span key={lineIndex} {...getLineProps({ line })} className="table-row">
                  <span className="table-cell select-none pr-4 text-right text-zinc-600" aria-hidden="true">
                    {lineIndex + 1}
                  </span>
                  <span className="table-cell">
                    {line.map((token, tokenIndex) => (
                      <span key={tokenIndex} {...getTokenProps({ token })} />
                    ))}
                  </span>
                </span>
              ))}
            </code>
          </pre>
        )}
      </Highlight>
    </div>
  )
}

export function HighlightedResponseRenderer({ content, sources }: { content: string; sources: Citation[] }) {
  const keywords = sources.flatMap((source) => [source.title, source.section ?? '', ...source.breadcrumb])
  const blocks: ReactNode[] = []
  const codePattern = /\x60\x60\x60([\w+-]*)\n?([\s\S]*?)\x60\x60\x60/g
  let cursor = 0
  let match: RegExpExecArray | null

  while ((match = codePattern.exec(content)) !== null) {
    if (match.index > cursor) {
      blocks.push(<p key={'text-' + cursor}>{renderText(content.slice(cursor, match.index), sources, keywords)}</p>)
    }
    blocks.push(<CodeBlock key={'code-' + match.index} language={match[1]} code={match[2]} />)
    cursor = codePattern.lastIndex
  }

  if (cursor < content.length) {
    blocks.push(<p key={'text-' + cursor}>{renderText(content.slice(cursor), sources, keywords)}</p>)
  }

  return (
    <div className="response-renderer">
      {blocks}
      <SourcesAccordion sources={sources} />
    </div>
  )
}
