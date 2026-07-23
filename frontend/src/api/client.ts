import type {
  AuthSession,
  ChatMode,
  ChatSession,
  ChatSessionDetail,
  Citation,
  Feedback,
  StreamCallbacks,
  TokenResponse,
  User,
} from './types'

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'https://localhost:7187'
export const API_BASE_URL = configuredBaseUrl.replace(/\/$/, '')

let accessToken: string | null = null

export class ApiError extends Error {
  status: number

  constructor(message: string, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export class AuthenticationError extends ApiError {
  constructor(message = 'Your session has expired. Please sign in again.') {
    super(message, 401)
    this.name = 'AuthenticationError'
  }
}

export function beginGoogleLogin() {
  window.location.assign(`${API_BASE_URL}/api/auth/login/google`)
}

export function clearStoredAuth() {
  accessToken = null
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  try {
    const body = await response.json() as {
      detail?: string | Array<{ msg?: string }>
      message?: string
    }
    if (typeof body.message === 'string') return new ApiError(body.message, response.status)
    if (typeof body.detail === 'string') return new ApiError(body.detail, response.status)
    if (Array.isArray(body.detail)) {
      const detail = body.detail.map((item) => item.msg).filter(Boolean).join(', ')
      if (detail) return new ApiError(detail, response.status)
    }
  } catch {
    // Use the HTTP status fallback for non-JSON proxy errors.
  }
  return new ApiError(response.statusText || 'The API request failed', response.status)
}

async function requestTokenRefresh(): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!response.ok) {
    clearStoredAuth()
    throw new AuthenticationError()
  }
  const tokens = await response.json() as TokenResponse
  accessToken = tokens.access_token
  return accessToken
}

function accessTokenNeedsRefresh(token: string, skewSeconds = 30): boolean {
  try {
    const payload = token.split('.')[1]
    if (!payload) return false
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')
    const claims = JSON.parse(window.atob(padded)) as { exp?: number }
    return typeof claims.exp === 'number'
      && claims.exp <= Math.floor(Date.now() / 1000) + skewSeconds
  } catch {
    return true
  }
}

let refreshInFlight: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  if (!refreshInFlight) {
    refreshInFlight = requestTokenRefresh().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

async function authorizedFetch(
  path: string,
  init: RequestInit = {},
  mayRefresh = true,
): Promise<Response> {
  let token = accessToken
  if (!token || (mayRefresh && accessTokenNeedsRefresh(token))) {
    token = await refreshAccessToken()
  }
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: 'include',
  })
  if (response.status === 401 && mayRefresh) {
    token = await refreshAccessToken()
    headers.set('Authorization', `Bearer ${token}`)
    return authorizedFetch(path, { ...init, headers }, false)
  }
  if (!response.ok) throw await errorFromResponse(response)
  return response
}

export async function getProfile(): Promise<User> {
  const response = await authorizedFetch('/api/auth/me')
  return response.json() as Promise<User>
}

export async function restoreSession(): Promise<AuthSession> {
  await refreshAccessToken()
  const profile = await getProfile()
  return {
    email: profile.email,
    fullName: profile.display_name ?? profile.email.split('@')[0] ?? 'User',
    avatarUrl: profile.avatar_url,
  }
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/api/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    })
  } finally {
    clearStoredAuth()
  }
}

export async function listSessions(mode?: ChatMode): Promise<ChatSession[]> {
  const query = mode ? `?mode=${encodeURIComponent(mode)}` : ''
  const response = await authorizedFetch(`/api/rag/history/sessions${query}`)
  return response.json() as Promise<ChatSession[]>
}

export async function getSession(sessionId: string): Promise<ChatSessionDetail> {
  const response = await authorizedFetch(
    `/api/rag/history/sessions/${encodeURIComponent(sessionId)}`,
  )
  return response.json() as Promise<ChatSessionDetail>
}

export async function deleteSession(sessionId: string): Promise<void> {
  await authorizedFetch(`/api/rag/history/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })
}

export async function saveFeedback(
  messageId: string,
  direction: 'up' | 'down',
  chips: string[] = [],
  comment = '',
): Promise<Feedback> {
  const response = await authorizedFetch(
    `/api/rag/feedback/messages/${encodeURIComponent(messageId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ direction, chips, comment }),
    },
  )
  return response.json() as Promise<Feedback>
}

type SseFrame = { event: string; data: string }

function parseFrame(block: string): SseFrame | null {
  let event = 'message'
  const data: string[] = []
  for (const rawLine of block.split(/\r?\n/)) {
    if (!rawLine || rawLine.startsWith(':')) continue
    const separator = rawLine.indexOf(':')
    const field = separator === -1 ? rawLine : rawLine.slice(0, separator)
    let value = separator === -1 ? '' : rawLine.slice(separator + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    if (field === 'data') data.push(value)
  }
  return data.length ? { event, data: data.join('\n') } : null
}

export async function streamChat(
  mode: ChatMode,
  message: string,
  sessionId: string | null,
  callbacks: StreamCallbacks,
  options: { regenerateMessageId?: string; signal?: AbortSignal } = {},
): Promise<void> {
  const endpoint = mode === 'general'
    ? '/api/rag/general/stream'
    : '/api/rag/document/stream'
  const response = await authorizedFetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      regenerate_message_id: options.regenerateMessageId ?? null,
    }),
    signal: options.signal,
  })
  if (!response.body) throw new ApiError('The browser did not receive a response stream')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed = false

  const consume = (block: string) => {
    const frame = parseFrame(block)
    if (!frame) return
    const payload = JSON.parse(frame.data) as {
      sources?: Citation[]
      mode?: 'fast' | 'complex'
      chat_mode?: ChatMode
      content?: string
      session_id?: string
      message_id?: string
      reply_to_message_id?: string
      version?: number
      web_enabled?: boolean
      detail?: string
    }
    if (frame.event === 'metadata') callbacks.onMetadata(payload.sources ?? [])
    if (frame.event === 'started' && payload.session_id) {
      callbacks.onStarted({
        sessionId: payload.session_id,
        chatMode: payload.chat_mode ?? mode,
        responseMode: payload.mode,
        replyToMessageId: payload.reply_to_message_id ?? '',
        version: payload.version ?? 1,
        webEnabled: payload.web_enabled,
      })
    }
    if (frame.event === 'delta') callbacks.onDelta(payload.content ?? '')
    if (frame.event === 'done' && payload.session_id) {
      completed = true
      callbacks.onDone({
        sessionId: payload.session_id,
        messageId: payload.message_id ?? '',
        replyToMessageId: payload.reply_to_message_id ?? '',
        version: payload.version ?? 1,
      })
    }
    if (frame.event === 'error') throw new ApiError(payload.detail ?? 'The chat stream failed')
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    let boundary = buffer.match(/\r?\n\r?\n/)
    while (boundary?.index !== undefined) {
      const index = boundary.index
      consume(buffer.slice(0, index))
      buffer = buffer.slice(index + boundary[0].length)
      boundary = buffer.match(/\r?\n\r?\n/)
    }
    if (done) break
  }
  if (buffer.trim()) consume(buffer)
  if (!completed) throw new ApiError('The chat stream ended before completion')
}
