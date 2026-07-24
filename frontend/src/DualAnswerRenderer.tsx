import { useState } from 'react'
import type { AnswerId, Citation, DualAnswerCandidate } from './api/types'
import { HighlightedResponseRenderer as ResponseRenderer } from './components/HighlightedResponseRenderer'

interface DualAnswerRendererProps {
  generationId: string
  answers: DualAnswerCandidate[]
  sources: Citation[]
  selectedAnswerId?: AnswerId | null
  onSelect: (
    generationId: string,
    answerId: AnswerId,
  ) => Promise<void> | void
}

export function DualAnswerRenderer({
  generationId,
  answers,
  sources,
  selectedAnswerId = null,
  onSelect,
}: DualAnswerRendererProps) {
  const [selectingAnswerId, setSelectingAnswerId] =
    useState<AnswerId | null>(null)
  const [selectionError, setSelectionError] =
    useState<string | null>(null)

  async function handleSelect(answerId: AnswerId) {
    if (selectingAnswerId || selectedAnswerId) return

    setSelectingAnswerId(answerId)
    setSelectionError(null)

    try {
      await onSelect(generationId, answerId)
    } catch (error) {
      setSelectionError(
        error instanceof Error
          ? error.message
          : 'The answer could not be selected.',
      )
    } finally {
      setSelectingAnswerId(null)
    }
  }

  if (answers.length === 0) return null

  return (
    <section
      className="dual-answer"
      aria-label="Generated answer choices"
    >
      {answers.length > 1 && !selectedAnswerId && (
        <header className="dual-answer__header">
          <h2>Choose your preferred answer</h2>
          <p>
            Both answers were generated independently. Select one to
            continue the conversation.
          </p>
        </header>
      )}

      <div
        className={
          answers.length > 1
            ? 'dual-answer__grid'
            : 'dual-answer__grid dual-answer__grid--single'
        }
      >
        {answers.map((answer) => {
          const isSelected = selectedAnswerId === answer.id
          const isSelecting = selectingAnswerId === answer.id
          const anotherAnswerSelected =
            selectedAnswerId !== null && !isSelected

          return (
            <article
              className={[
                'dual-answer__card',
                isSelected
                  ? 'dual-answer__card--selected'
                  : '',
                anotherAnswerSelected
                  ? 'dual-answer__card--muted'
                  : '',
              ]
                .filter(Boolean)
                .join(' ')}
              key={answer.id}
            >
              <div className="dual-answer__card-header">
                <h3>{answer.label}</h3>

                {isSelected && (
                  <span className="dual-answer__selected-badge">
                    Selected
                  </span>
                )}
              </div>

              {answer.error ? (
                <div
                  className="dual-answer__answer-error"
                  role="alert"
                >
                  {answer.error}
                </div>
              ) : (
                <>
                  <ResponseRenderer
                    content={answer.content}
                    sources={sources}
                  />

                  {!answer.completed && (
                    <div
                      className="dual-answer__streaming"
                      aria-live="polite"
                    >
                      Generating…
                    </div>
                  )}
                </>
              )}

              {answers.length > 1 &&
                !answer.error &&
                !selectedAnswerId && (
                  <button
                    className="dual-answer__select-button"
                    type="button"
                    disabled={
                      !answer.completed ||
                      !answer.content.trim() ||
                      selectingAnswerId !== null
                    }
                    onClick={() => handleSelect(answer.id)}
                  >
                    {isSelecting
                      ? 'Selecting…'
                      : 'Choose this answer'}
                  </button>
                )}
            </article>
          )
        })}
      </div>

      {selectionError && (
        <p
          className="dual-answer__selection-error"
          role="alert"
        >
          {selectionError}
        </p>
      )}
    </section>
  )
}
