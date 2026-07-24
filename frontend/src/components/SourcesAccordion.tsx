import { ExternalLink, FileText } from 'lucide-react'
import type { Citation } from '../api/types'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from './ui/accordion'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'

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
    <Accordion type="single" collapsible className="mt-5 rounded-xl border bg-muted/25 px-4">
      <AccordionItem value="sources" className="border-0">
        <AccordionTrigger className="py-3 text-sm hover:no-underline">
          <span className="flex items-center gap-2">
            <FileText className="size-4 text-primary" aria-hidden="true" />
            {sources.length} {sources.length === 1 ? 'source' : 'sources'}
          </span>
        </AccordionTrigger>
        <AccordionContent>
          <div className="grid gap-3 pb-2">
            {sources.map((source, index) => {
              const href = safeHttpUrl(source.source_url)
              const location = [
                source.page_number === null ? null : 'Page ' + source.page_number,
                source.section,
                source.breadcrumb.length ? source.breadcrumb.join(' / ') : null,
                source.chunk_id ? 'Chunk ' + source.chunk_id : null,
              ].filter(Boolean).join(' | ')
              const normalizedChunk = (source.summary || source.chunk_text).replace(/\s+/g, ' ').trim()
              const excerpt = normalizedChunk.length > 220
                ? normalizedChunk.slice(0, 217).trimEnd() + '...'
                : normalizedChunk
              const confidence = source.relevance ?? source.score

              return (
                <Card key={source.document_id + '-' + index} className="gap-3 py-4 shadow-none">
                  <CardHeader className="px-4">
                    <div className="flex items-start justify-between gap-3">
                      <CardTitle className="text-sm leading-5">{index + 1}. {source.title}</CardTitle>
                      {confidence !== null && (
                        <Badge variant="secondary" className="shrink-0">
                          {Math.round(confidence * 100)}%
                        </Badge>
                      )}
                    </div>
                    {location && <p className="text-xs text-muted-foreground">{location}</p>}
                  </CardHeader>
                  <CardContent className="space-y-3 px-4">
                    <p className="text-sm leading-6 text-muted-foreground">{excerpt}</p>
                    {href ? (
                      <Button variant="outline" size="sm" asChild>
                        <a href={href} target="_blank" rel="noreferrer">
                          Open source <ExternalLink aria-hidden="true" />
                        </a>
                      </Button>
                    ) : source.file_path ? (
                      <code className="block overflow-x-auto rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                        {source.file_path}
                      </code>
                    ) : null}
                  </CardContent>
                </Card>
              )
            })}
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}
