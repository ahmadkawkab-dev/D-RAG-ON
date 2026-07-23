import { useEffect, useState } from 'react'
import {
  BookOpenText,
  Check,
  ChevronLeft,
  ChevronRight,
  FileSearch,
  MessageSquareText,
  Sparkles,
  X,
} from 'lucide-react'
import { Button } from './ui/button'

type OnboardingGuideProps = {
  open: boolean
  storageKey: string
  onOpenChange: (open: boolean) => void
}

const steps = [
  {
    title: 'Choose your workspace',
    description:
      'Use General for open-domain questions. Use Documents when answers should be grounded in your uploaded knowledge.',
    icon: BookOpenText,
  },
  {
    title: 'Start or reopen a chat',
    description:
      'Create a new conversation from the sidebar, or search your saved history and continue where you stopped.',
    icon: MessageSquareText,
  },
  {
    title: 'Ask a focused question',
    description:
      'Type your request in the message box. Press Enter to send, or Shift + Enter to add another line.',
    icon: Sparkles,
  },
  {
    title: 'Review and continue',
    description:
      'Check sources, provide feedback, export useful conversations, and choose one response whenever two alternatives appear.',
    icon: FileSearch,
  },
] as const

export function OnboardingGuide({
  open,
  storageKey,
  onOpenChange,
}: OnboardingGuideProps) {
  const [stepIndex, setStepIndex] = useState(0)

  useEffect(() => {
    if (open) {
      setStepIndex(0)
    }
  }, [open])

  useEffect(() => {
    if (!open) return

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return

      window.localStorage.setItem(storageKey, 'completed')
      onOpenChange(false)
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onOpenChange, open, storageKey])

  if (!open) return null

  const step = steps[stepIndex]
  const StepIcon = step.icon
  const isFirstStep = stepIndex === 0
  const isLastStep = stepIndex === steps.length - 1

  const dismiss = () => {
    window.localStorage.setItem(storageKey, 'completed')
    onOpenChange(false)
  }

  const next = () => {
    if (isLastStep) {
      dismiss()
      return
    }

    setStepIndex((current) => current + 1)
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/55 p-4 backdrop-blur-sm"
      role="presentation"
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-guide-title"
        aria-describedby="onboarding-guide-description"
        className="w-full max-w-lg overflow-hidden rounded-3xl border bg-background shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b px-6 py-5">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
              <Sparkles className="size-3.5" aria-hidden="true" />
              Quick start
            </div>
            <h2
              id="onboarding-guide-title"
              className="text-xl font-semibold tracking-tight"
            >
              Welcome to Pixel Mind
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Four steps to get productive.
            </p>
          </div>

          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={dismiss}
            aria-label="Close guide"
          >
            <X aria-hidden="true" />
          </Button>
        </header>

        <div className="px-6 pt-5">
          <div
            className="grid grid-cols-4 gap-2"
            aria-label={`Step ${stepIndex + 1} of ${steps.length}`}
          >
            {steps.map((item, index) => (
              <div
                key={item.title}
                className={[
                  'h-1.5 rounded-full transition-colors',
                  index <= stepIndex ? 'bg-primary' : 'bg-muted',
                ].join(' ')}
              />
            ))}
          </div>
        </div>

        <div className="px-6 py-8">
          <div className="mb-5 flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary ring-1 ring-primary/15">
            <StepIcon className="size-7" aria-hidden="true" />
          </div>

          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            Step {stepIndex + 1} of {steps.length}
          </p>

          <h3 className="text-2xl font-semibold tracking-tight">
            {step.title}
          </h3>

          <p
            id="onboarding-guide-description"
            className="mt-3 text-sm leading-6 text-muted-foreground"
          >
            {step.description}
          </p>
        </div>

        <footer className="flex items-center justify-between gap-3 border-t bg-muted/25 px-6 py-4">
          <Button
            type="button"
            variant="ghost"
            onClick={dismiss}
          >
            Skip guide
          </Button>

          <div className="flex items-center gap-2">
            {!isFirstStep && (
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  setStepIndex((current) => Math.max(0, current - 1))
                }
              >
                <ChevronLeft aria-hidden="true" />
                Back
              </Button>
            )}

            <Button type="button" onClick={next}>
              {isLastStep ? (
                <>
                  <Check aria-hidden="true" />
                  Start using Pixel Mind
                </>
              ) : (
                <>
                  Next
                  <ChevronRight aria-hidden="true" />
                </>
              )}
            </Button>
          </div>
        </footer>
      </section>
    </div>
  )
}