import { useState } from 'react'
import { Download, FileText, LoaderCircle } from 'lucide-react'
import { toast } from 'sonner'
import type { ChatMessage } from '../api/types'
import {
  exportConversationMarkdown,
  exportConversationPdf,
} from '../lib/conversation-export'
import { Button } from './ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from './ui/tooltip'

export function ConversationExportMenu({
  title,
  messages,
  disabled = false,
}: {
  title: string
  messages: ChatMessage[]
  disabled?: boolean
}) {
  const [exporting, setExporting] = useState<'pdf' | null>(null)

  const exportMarkdown = () => {
    try {
      exportConversationMarkdown(title, messages)
      toast.success('Markdown exported')
    } catch {
      toast.error('Unable to export Markdown')
    }
  }

  const exportPdf = async () => {
    setExporting('pdf')
    try {
      await exportConversationPdf(title, messages)
      toast.success('PDF exported')
    } catch {
      toast.error('Unable to export PDF')
    } finally {
      setExporting(null)
    }
  }

  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={disabled || exporting !== null}
              aria-label="Export conversation"
            >
              {exporting ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Download aria-hidden="true" />}
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>Export conversation</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuLabel>Export conversation</DropdownMenuLabel>
        <DropdownMenuItem onSelect={exportMarkdown}>
          <FileText aria-hidden="true" />
          Markdown (.md)
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void exportPdf()}>
          <FileText aria-hidden="true" />
          PDF (.pdf)
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
