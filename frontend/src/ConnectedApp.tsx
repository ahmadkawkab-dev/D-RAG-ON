import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import {
  ApiError,
  AuthenticationError,
  clearStoredAuth,
  deleteSession,
  getSession,
  getStoredAuth,
  listSessions,
  streamChat,
} from './api/client'
import type { AuthSession, ChatMessage, ChatSession } from './api/types'
import { AuthPanel } from './components/AuthPanel'
import { PixelBot } from './components/PixelBot'
import { SourcesAccordion } from './components/SourcesAccordion'
import './App.css'

type UiMessage = ChatMessage & { pending?: boolean }

const suggestions = [
  { icon: '✦', label: 'Summarize a document', prompt: 'Summarize the key ideas in my knowledge base.' },
  { icon: '⌁', label: 'Find a connection', prompt: 'Find connections between the documents in my knowledge base.' },
  { icon: '◇', label: 'Explain a concept', prompt: 'Explain the most important concept in simple terms.' },
  { icon: '↗', label: 'Draft from sources', prompt: 'Draft a short brief using my indexed sources.' },
]

function timestamp(value: string) {
  return new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function isToday(value: string) {
  const date = new Date(value)
  return date.toDateString() === new Date().toDateString()
}

function readableError(error: unknown) {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error && error.name === 'AbortError') return ''
  if (error instanceof TypeError) return 'Unable to reach the API. Check that FastAPI is running and the API URL is correct.'
  return 'Something went wrong while contacting the API.'
}

function ConnectedApp() {
  const [auth, setAuth] = useState<AuthSession | null>(() => getStoredAuth())
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<UiMessage[]>([])
  const [input, setInput] = useState('')
  const [search, setSearch] = useState('')
  const [isThinking, setIsThinking] = useState(false)
  const [runningSessionId, setRunningSessionId] = useState<string | null>(null)
  const [historyLoading, setHistoryLoading] = useState(Boolean(auth))
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  const streamController = useRef<AbortController | null>(null)
  const activeIdRef = useRef<string | null>(null)
  const backgroundMessages = useRef(new Map<string, UiMessage[]>())

  const activeSession = sessions.find((session) => session.id === activeId)
  const filteredSessions = sessions.filter((session) => session.title.toLowerCase().includes(search.trim().toLowerCase()))
  const todaySessions = filteredSessions.filter((session) => isToday(session.updated_at))
  const earlierSessions = filteredSessions.filter((session) => !isToday(session.updated_at))

  useEffect(() => {
    if (!auth) return
    let cancelled = false
    listSessions()
      .then((value) => { if (!cancelled) setSessions(value) })
      .catch((caught) => {
        if (cancelled) return
        if (caught instanceof AuthenticationError) {
          clearStoredAuth()
          setAuth(null)
        }
        setError(readableError(caught))
      })
      .finally(() => { if (!cancelled) setHistoryLoading(false) })
    return () => { cancelled = true }
  }, [auth])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isThinking])

  useEffect(() => () => streamController.current?.abort(), [])
  useEffect(() => {
    activeIdRef.current = activeId
  }, [activeId])


  if (!auth) return <AuthPanel onAuthenticated={setAuth} />

  const handleApiError = (caught: unknown) => {
    if (caught instanceof AuthenticationError) {
      clearStoredAuth()
      setAuth(null)
    }
    const message = readableError(caught)
    if (message) setError(message)
  }

  const refreshSessionList = async () => {
    setSessions(await listSessions())
  }

  const startNewChat = () => {
    setActiveId(null)
    setMessages([])
    activeIdRef.current = null
    setInput('')
    setError('')
    setSidebarOpen(false)
  }

  const openSession = async (sessionId: string) => {
    if (sessionId === activeId) {
      setSidebarOpen(false)
      return
    }
    setError('')
    setHistoryLoading(true)
    const buffered = backgroundMessages.current.get(sessionId)
    if (buffered) {
      activeIdRef.current = sessionId
      setActiveId(sessionId)
      setMessages(buffered)
      setSidebarOpen(false)
      setHistoryLoading(false)
      return
    }
    try {
      const detail = await getSession(sessionId)
      setActiveId(sessionId)
      activeIdRef.current = sessionId
      setMessages(detail.messages)
      setSidebarOpen(false)
    } catch (caught) {
      handleApiError(caught)
    } finally {
      setHistoryLoading(false)
    }
  }

  const removeActiveSession = async () => {
    if (!activeId || isThinking || !window.confirm('Delete this conversation and all of its messages?')) return
    try {
      await deleteSession(activeId)
      setActiveId(null)
      setMessages([])
      await refreshSessionList()
    } catch (caught) {
      handleApiError(caught)
    }
  }

  const signOut = () => {
    streamController.current?.abort()
    clearStoredAuth()
    setAuth(null)
    setSessions([])
    backgroundMessages.current.clear()
    setMessages([])
    setActiveId(null)
    activeIdRef.current = null
  }

  const sendMessage = async (rawInput = input) => {
    const content = rawInput.trim()
    if (!content || isThinking) return

    const originSessionId = activeId
    let taskSessionId = activeId
    const requestId = crypto.randomUUID()
    const now = new Date().toISOString()
    const userMessage: UiMessage = {
      id: `${requestId}-user`, session_id: activeId ?? '', role: 'user', content, sources: [], timestamp: now,
    }
    const assistantMessage: UiMessage = {
      id: `${requestId}-assistant`, session_id: activeId ?? '', role: 'assistant', content: '', sources: [], timestamp: now, pending: true,
    }
    let taskMessages = [...messages, userMessage, assistantMessage]

    const updateTaskMessages = (update: (current: UiMessage[]) => UiMessage[]) => {
      taskMessages = update(taskMessages)
      if (taskSessionId) backgroundMessages.current.set(taskSessionId, taskMessages)
      const stillViewingTask = activeIdRef.current === taskSessionId
        || (taskSessionId === null && activeIdRef.current === originSessionId)
      if (stillViewingTask) setMessages(taskMessages)
    }

    setMessages(taskMessages)
    if (taskSessionId) backgroundMessages.current.set(taskSessionId, taskMessages)
    setRunningSessionId(taskSessionId)
    setInput('')
    setError('')
    setIsThinking(true)
    const controller = new AbortController()
    streamController.current = controller
    let completedSessionId: string | null = null

    try {
      await streamChat(content, activeId, {
        onStarted: (sessionId) => {
          const previousTaskId = taskSessionId
          taskSessionId = sessionId
          taskMessages = taskMessages.map((message) => ({ ...message, session_id: sessionId }))
          if (previousTaskId && previousTaskId !== sessionId) {
            backgroundMessages.current.delete(previousTaskId)
          }
          backgroundMessages.current.set(sessionId, taskMessages)
          setRunningSessionId(sessionId)
          setSessions((current) => current.some((session) => session.id === sessionId)
            ? current
            : [{
                id: sessionId,
                title: content.length > 48 ? `${content.slice(0, 48)}...` : content,
                created_at: now,
                updated_at: now,
              }, ...current])
          if (activeIdRef.current === originSessionId) {
            activeIdRef.current = sessionId
            setActiveId(sessionId)
            setMessages(taskMessages)
          }
        },
        onMetadata: (sources) => updateTaskMessages((current) => current.map((message) =>
          message.id === assistantMessage.id ? { ...message, sources } : message)),
        onDelta: (delta) => updateTaskMessages((current) => current.map((message) =>
          message.id === assistantMessage.id ? { ...message, content: message.content + delta } : message)),
        onDone: (sessionId) => { completedSessionId = sessionId },
      }, controller.signal)

      if (!completedSessionId) throw new ApiError('The API did not return a session identifier')
      const [detail, updatedSessions] = await Promise.all([getSession(completedSessionId), listSessions()])
      backgroundMessages.current.delete(completedSessionId)
      if (activeIdRef.current === completedSessionId) setMessages(detail.messages)
      setSessions(updatedSessions)
    } catch (caught) {
      updateTaskMessages((current) => current
        .filter((message) => message.id !== assistantMessage.id || message.content.length > 0)
        .map((message) => ({ ...message, pending: false })))
      handleApiError(caught)
      try {
        await refreshSessionList()
      } catch {
        // Preserve the original streaming error.
      }
    } finally {
      streamController.current = null
      setRunningSessionId(null)
      setIsThinking(false)
    }
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    void sendMessage()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void sendMessage()
    }
  }

  const renderSessionGroup = (label: string, group: ChatSession[]) => {
    if (!group.length) return null
    return (
      <>
        <p className={`nav-label ${label === 'EARLIER' ? 'nav-label--spaced' : ''}`}>{label}</p>
        {group.map((session) => (
          <button
            className={`conversation-item ${session.id === activeId ? 'conversation-item--active' : ''}`}
            type="button"
            key={session.id}
            onClick={() => void openSession(session.id)}
          >
            <span className="chat-pixel" aria-hidden="true">□</span>
            <span>{session.title}</span>
            {(session.id === activeId || session.id === runningSessionId) && <i aria-label={session.id === runningSessionId ? 'Answer running' : 'Current conversation'}>●</i>}
          </button>
        ))}
      </>
    )
  }

  const initials = auth.fullName.trim().slice(0, 1).toUpperCase() || 'U'

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? 'sidebar--open' : ''}`}>
        <div className="brand-row">
          <div className="brand-mark"><PixelBot small /></div>
          <div><strong>PIXEL MIND</strong><span>KNOWLEDGE BOT</span></div>
          <button className="icon-button close-sidebar" type="button" onClick={() => setSidebarOpen(false)} aria-label="Close menu">×</button>
        </div>

        <button className="new-chat-button" type="button" onClick={startNewChat}>
          <span>＋</span> NEW CHAT
        </button>

        <label className="search-field">
          <span aria-hidden="true">⌕</span>
          <input type="search" placeholder="SEARCH CHATS" aria-label="Search chats" value={search} onChange={(event) => setSearch(event.target.value)} />
          <kbd>/</kbd>
        </label>

        <nav className="conversation-list" aria-label="Conversation history">
          {historyLoading && !sessions.length ? <p className="history-status">LOADING HISTORY...</p> : null}
          {!historyLoading && !filteredSessions.length ? <p className="history-status">NO SAVED CHATS</p> : null}
          {renderSessionGroup('TODAY', todaySessions)}
          {renderSessionGroup('EARLIER', earlierSessions)}
        </nav>

        <div className="sidebar-footer">
          <button type="button"><span>?</span> HELP CENTER</button>
          <button type="button"><span>⚙</span> SETTINGS</button>
          <div className="user-card">
            <div className="pixel-avatar" aria-hidden="true">{initials}</div>
            <div><strong>{auth.fullName.toUpperCase()}</strong><span>{auth.email}</span></div>
            <button type="button" onClick={signOut} aria-label="Sign out" title="Sign out">↪</button>
          </div>
        </div>
      </aside>

      {sidebarOpen && <button className="sidebar-backdrop" type="button" onClick={() => setSidebarOpen(false)} aria-label="Close menu" />}

      <main className="chat-panel">
        <header className="topbar">
          <button className="icon-button menu-button" type="button" onClick={() => setSidebarOpen(true)} aria-label="Open menu">☰</button>
          <div className="chat-title">
            <span className="title-pixel" />
            <div>
              <strong>{activeSession?.title ?? 'NEW CHAT'}</strong>
              <span><i /> {isThinking ? 'ANSWER RUNNING IN BACKGROUND' : historyLoading ? 'SYNCING' : 'SYSTEM ONLINE'}</span>
            </div>
          </div>
          <div className="topbar-actions">
            <button className="pixel-action" type="button" onClick={() => void removeActiveSession()} disabled={!activeId || isThinking} aria-label="Delete conversation" title="Delete conversation">⌫</button>
            <button className="pixel-action" type="button" onClick={signOut} aria-label="Sign out" title="Sign out">↪</button>
          </div>
        </header>

        <section className={`chat-stage ${messages.length ? 'chat-stage--conversation' : ''}`}>
          {messages.length === 0 ? (
            <div className="welcome-state">
              <PixelBot />
              <p className="eyebrow">READY TO SEARCH</p>
              <h1>WHAT CAN I HELP<br />YOU DISCOVER?</h1>
              <p className="intro">Ask a question and I’ll search your knowledge base<br />for the most relevant answer.</p>
              {error && <p className="api-error stage-error" role="alert">{error}</p>}
              <div className="suggestion-grid">
                {suggestions.map((suggestion) => (
                  <button type="button" key={suggestion.label} disabled={isThinking} onClick={() => void sendMessage(suggestion.prompt)}>
                    <span>{suggestion.icon}</span><strong>{suggestion.label}</strong><i>↗</i>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="message-list" aria-live="polite">
              {error && <p className="api-error stage-error" role="alert">{error}</p>}
              {messages.map((message) => (
                <article className={`message message--${message.role}`} key={message.id}>
                  <div className="message-avatar">{message.role === 'assistant' ? <PixelBot small /> : initials}</div>
                  <div>
                    <div className="message-meta"><strong>{message.role === 'assistant' ? 'PIXEL MIND' : 'YOU'}</strong><time>{timestamp(message.timestamp)}</time></div>
                    {message.content ? <p>{message.content}</p> : message.pending ? <div className="thinking" aria-label="Generating response"><i /><i /><i /></div> : null}
                    <SourcesAccordion sources={message.sources} />
                  </div>
                </article>
              ))}
              <div ref={endRef} />
            </div>
          )}
        </section>

        <div className="composer-wrap">
          <form className="composer" onSubmit={handleSubmit}>
            <button className="attach-button" type="button" aria-label="Attach document" title="Document upload is planned for a future release">＋</button>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="ASK YOUR KNOWLEDGE BASE..."
              aria-label="Message"
              rows={1}
              disabled={isThinking}
            />
            <button className="send-button" type="submit" disabled={!input.trim() || isThinking} aria-label="Send message">↑</button>
          </form>
          <p className="composer-note"><span>ENTER</span> TO SEND <b>·</b> <span>SHIFT + ENTER</span> FOR NEW LINE</p>
        </div>
      </main>
    </div>
  )
}

export default ConnectedApp
