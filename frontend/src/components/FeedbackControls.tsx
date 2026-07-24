import { useState } from 'react'
import { LoaderCircle, ThumbsDown, ThumbsUp } from 'lucide-react'
import { saveFeedback } from '../api/client'
import type { ChatMessage, Feedback } from '../api/types'
import { Button } from './ui/button'
import { Collapsible, CollapsibleContent } from './ui/collapsible'
import { Textarea } from './ui/textarea'
import { ToggleGroup, ToggleGroupItem } from './ui/toggle-group'
import { Tooltip, TooltipContent, TooltipTrigger } from './ui/tooltip'

const reasons = [
  'Inaccurate',
  'Not relevant',
  'Missing citation',
  'Too long',
  'Off-topic',
  'Hallucinated',
]

export function FeedbackControls({
  message,
  onSaved,
}: {
  message: ChatMessage
  onSaved: (feedback: Feedback) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [chips, setChips] = useState<string[]>(message.feedback?.chips ?? [])
  const [comment, setComment] = useState(message.feedback?.comment ?? '')
  const [saving, setSaving] = useState(false)

  const submit = async (direction: 'up' | 'down', detailed = false) => {
    if (message.pending || saving) return
    if (direction === 'down' && !detailed && !expanded) {
      setExpanded(true)
      return
    }
    setSaving(true)
    try {
      onSaved(await saveFeedback(message.id, direction, chips, comment))
      setExpanded(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Collapsible open={expanded} onOpenChange={setExpanded} className="mt-4">
      <div className="flex items-center gap-1">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={message.feedback?.direction === 'up' ? 'secondary' : 'ghost'}
              size="icon-sm"
              type="button"
              disabled={saving || message.pending}
              onClick={() => void submit('up')}
              aria-label="Helpful answer"
            >
              <ThumbsUp aria-hidden="true" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Helpful answer</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={message.feedback?.direction === 'down' ? 'secondary' : 'ghost'}
              size="icon-sm"
              type="button"
              disabled={saving || message.pending}
              onClick={() => void submit('down')}
              aria-label="Unhelpful answer"
            >
              <ThumbsDown aria-hidden="true" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Suggest an improvement</TooltipContent>
        </Tooltip>
      </div>

      <CollapsibleContent>
        <div className="mt-3 max-w-2xl space-y-4 rounded-xl border bg-muted/40 p-4">
          <div>
            <p className="text-sm font-medium">What should improve?</p>
            <p className="text-xs text-muted-foreground">Select any issues that apply.</p>
          </div>
          <ToggleGroup
            type="multiple"
            variant="outline"
            value={chips}
            onValueChange={setChips}
            className="flex flex-wrap justify-start"
            aria-label="Feedback reasons"
          >
            {reasons.map((reason) => (
              <ToggleGroupItem key={reason} value={reason} size="sm">
                {reason}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <Textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder="Optional note"
            maxLength={2000}
            aria-label="Optional feedback note"
          />
          <div className="flex justify-end">
            <Button type="button" size="sm" onClick={() => void submit('down', true)} disabled={saving}>
              {saving && <LoaderCircle className="animate-spin" aria-hidden="true" />}
              Save feedback
            </Button>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
