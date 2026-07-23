export type ChatMode = 'document' | 'general'
export type AnswerId = 'answer_a' | 'answer_b'

export type Citation = {
  document_id: string
  title: string
  source_url: string | null
  file_path: string | null
  page_number: number | null
  section: string | null
  chunk_id: string | null
  breadcrumb: string[]
  summary: string | null
  metadata: Record<string, unknown>
  chunk_text: string
  score: number | null
  relevance: number | null
}

export type ChatSession = {
  id: string
  title: string
  mode: ChatMode
  created_at: string
  updated_at: string
}

export type Feedback = {
  id: string
  message_id: string
  session_id: string
  mode: ChatMode
  direction: 'up' | 'down'
  chips: string[]
  comment: string
  created_at: string
  updated_at: string
}

export type ChatMessage = {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  sources: Citation[]
  timestamp: string
  reply_to_message_id: string | null
  version: number
  feedback: Feedback | null
  pending?: boolean
}

export type ChatSessionDetail = {
  session: ChatSession
  messages: ChatMessage[]
}

export type User = {
  id: string
  email: string
  display_name: string | null
  avatar_url: string | null
  roles: string[]
}

export type TokenResponse = {
  access_token: string
  token_type: string
  expires_in: number
}

export type AuthSession = {
  email: string
  fullName: string
  avatarUrl?: string | null
}

export type StreamStarted = {
  sessionId: string
  chatMode: ChatMode
  responseMode?: 'fast' | 'complex'
  replyToMessageId: string
  version: number
  webEnabled?: boolean
}

export type StreamDone = Pick<
  StreamStarted,
  'sessionId' | 'replyToMessageId' | 'version'
> & {
  messageId: string | null
  requiresSelection: boolean
}

export type StreamCallbacks = {
  onStarted: (event: StreamStarted) => void
  onMetadata: (sources: Citation[]) => void
  onDelta: (content: string) => void
  onDone: (event: StreamDone) => void
  onGenerationStarted?: (event: DualGenerationStarted) => void
  onAnswerStarted?: (event: DualAnswerStarted) => void
  onAnswerDelta?: (event: DualAnswerDelta) => void
  onAnswerDone?: (event: DualAnswerCompleted) => void
  onAnswerError?: (event: DualAnswerFailed) => void
  onGenerationDone?: (event: DualGenerationCompleted) => void
}


export type DualAnswerCandidate = {
  id: AnswerId
  label: string
  content: string
  completed: boolean
  error?: string
}

export type DualAnswerGeneration = {
  generationId: string
  answers: DualAnswerCandidate[]
  sources: Citation[]
  selectedAnswerId: AnswerId | null
  completed: boolean
}

export type DualGenerationStarted = {
  generationId: string
  answerCount: number
  sources: Citation[]
}

export type DualAnswerStarted = {
  generationId: string
  answerId: AnswerId
  label: string
}

export type DualAnswerDelta = DualAnswerStarted & {
  content: string
}

export type DualAnswerCompleted = {
  generationId: string
  answerId: AnswerId
}

export type DualAnswerFailed = DualAnswerCompleted & {
  label: string
  error: string
}

export type DualGenerationCompleted = {
  generationId: string
  availableAnswerIds: AnswerId[]
}

export type GeneralAnswerSelectionResponse = ChatMessage