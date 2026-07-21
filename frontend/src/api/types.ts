export type Citation = {
  document_id: string
  title: string
  source_url: string | null
  file_path: string | null
  page_number: number | null
  section: string | null
  chunk_text: string
  score: number | null
  relevance: number | null
}

export type ChatSession = {
  id: string
  title: string
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
}

export type ChatSessionDetail = {
  session: ChatSession
  messages: ChatMessage[]
}

export type User = {
  id: string
  email: string
  full_name: string
  created_at: string
}

export type TokenResponse = {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export type AuthSession = {
  email: string
  fullName: string
  tokens: TokenResponse
}

export type StreamCallbacks = {
  onStarted: (sessionId: string, mode: 'fast' | 'complex') => void
  onMetadata: (sources: Citation[]) => void
  onDelta: (content: string) => void
  onDone: (sessionId: string) => void
}
