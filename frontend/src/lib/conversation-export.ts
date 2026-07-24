import type { ChatMessage } from '../api/types'

export type ExportableMessage = Pick<
  ChatMessage,
  'role' | 'content' | 'timestamp' | 'sources'
>

function safeFilename(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64) || 'conversation'
}

function sourceLabel(message: ExportableMessage) {
  return message.sources.map((source, index) => {
    const location = [source.section, source.page_number ? `page ${source.page_number}` : '']
      .filter(Boolean)
      .join(', ')
    const target = source.source_url ?? source.file_path
    const suffix = location ? ` (${location})` : ''
    return target
      ? `${index + 1}. [${source.title}](${target})${suffix}`
      : `${index + 1}. ${source.title}${suffix}`
  })
}

export function conversationMarkdown(title: string, messages: ExportableMessage[]) {
  const sections = messages.map((message) => {
    const role = message.role === 'assistant' ? 'Assistant' : 'You'
    const time = new Date(message.timestamp).toLocaleString()
    const sources = sourceLabel(message)
    return [
      `## ${role}`,
      `_${time}_`,
      '',
      message.content,
      ...(sources.length ? ['', '### Sources', ...sources] : []),
    ].join('\n')
  })

  return [
    `# ${title}`,
    '',
    `Exported ${new Date().toLocaleString()}`,
    '',
    ...sections.flatMap((section) => [section, '', '---', '']),
  ].join('\n').replace(/\n---\n\s*$/, '\n')
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function exportConversationMarkdown(title: string, messages: ExportableMessage[]) {
  const markdown = conversationMarkdown(title, messages)
  downloadBlob(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }), `${safeFilename(title)}.md`)
}

export async function exportConversationPdf(title: string, messages: ExportableMessage[]) {
  const { jsPDF } = await import('jspdf')
  const document = new jsPDF({ unit: 'pt', format: 'a4' })
  const margin = 48
  const pageWidth = document.internal.pageSize.getWidth()
  const pageHeight = document.internal.pageSize.getHeight()
  const contentWidth = pageWidth - margin * 2
  let y = margin

  const ensureSpace = (height: number) => {
    if (y + height <= pageHeight - margin) return
    document.addPage()
    y = margin
  }

  const addText = (text: string, size: number, lineHeight: number, style: 'normal' | 'bold' = 'normal') => {
    document.setFont('helvetica', style)
    document.setFontSize(size)
    const lines = document.splitTextToSize(text || ' ', contentWidth) as string[]
    for (const line of lines) {
      ensureSpace(lineHeight)
      document.text(line, margin, y)
      y += lineHeight
    }
  }

  addText(title, 20, 26, 'bold')
  document.setTextColor(100)
  addText(`Exported ${new Date().toLocaleString()}`, 9, 14)
  document.setTextColor(20)
  y += 14

  for (const message of messages) {
    ensureSpace(42)
    addText(message.role === 'assistant' ? 'Assistant' : 'You', 12, 18, 'bold')
    document.setTextColor(105)
    addText(new Date(message.timestamp).toLocaleString(), 8, 12)
    document.setTextColor(20)
    y += 5
    addText(message.content, 10, 15)
    if (message.sources.length) {
      y += 7
      addText('Sources', 9, 14, 'bold')
      for (const source of sourceLabel(message)) addText(source, 8, 12)
    }
    y += 18
  }

  document.save(`${safeFilename(title)}.pdf`)
}
