import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import './App.css'

type Message = {
  id: number
  role: 'assistant' | 'user'
  content: string
  time: string
}

type Conversation = {
  id: number
  title: string
  messages: Message[]
}

const suggestions = [
  { icon: '✦', label: 'Summarize a document', prompt: 'Summarize the key ideas in my knowledge base.' },
  { icon: '⌁', label: 'Find a connection', prompt: 'Find connections between the documents in my knowledge base.' },
  { icon: '◇', label: 'Explain a concept', prompt: 'Explain the most important concept in simple terms.' },
  { icon: '↗', label: 'Draft from sources', prompt: 'Draft a short brief using my indexed sources.' },
]

const starterConversations: Conversation[] = [
  {
    id: 1,
    title: 'Getting started with RAG',
    messages: [
      {
        id: 1,
        role: 'assistant',
        content: 'Retrieval-augmented generation gives an AI relevant source material before it answers. Ask me about your indexed documents and I’ll help you explore them.',
        time: '09:41',
      },
    ],
  },
  { id: 2, title: 'CIS Controls overview', messages: [] },
  { id: 3, title: 'Document ingestion notes', messages: [] },
  { id: 4, title: 'Evaluation results', messages: [] },
]

function currentTime() {
  return new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

function PixelBot({ small = false }: { small?: boolean }) {
  return (
    <div className={`pixel-bot ${small ? 'pixel-bot--small' : ''}`} aria-hidden="true">
      <span className="bot-antenna" />
      <span className="bot-ear bot-ear--left" />
      <span className="bot-face">
        <i className="bot-eye bot-eye--left" />
        <i className="bot-eye bot-eye--right" />
        <i className="bot-mouth" />
      </span>
      <span className="bot-ear bot-ear--right" />
      {!small && <span className="bot-shadow" />}
    </div>
  )
}

function App() {
  const [conversations, setConversations] = useState(starterConversations)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [isThinking, setIsThinking] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  const activeConversation = conversations.find((conversation) => conversation.id === activeId)
  const messages = activeConversation?.messages ?? []

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, isThinking])

  const startNewChat = () => {
    setActiveId(null)
    setInput('')
    setSidebarOpen(false)
  }

  const sendMessage = (rawInput = input) => {
    const content = rawInput.trim()
    if (!content || isThinking) return

    const messageId = Math.max(0, ...conversations.flatMap((conversation) => conversation.messages.map((message) => message.id))) + 1
    const userMessage: Message = {
      id: messageId,
      role: 'user',
      content,
      time: currentTime(),
    }

    let conversationId = activeId
    if (conversationId === null) {
      conversationId = Math.max(0, ...conversations.map((conversation) => conversation.id)) + 1
      setActiveId(conversationId)
      setConversations((current) => [
        {
          id: conversationId as number,
          title: content.length > 34 ? `${content.slice(0, 34)}…` : content,
          messages: [userMessage],
        },
        ...current,
      ])
    } else {
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === conversationId
            ? { ...conversation, messages: [...conversation.messages, userMessage] }
            : conversation,
        ),
      )
    }

    setInput('')
    setIsThinking(true)

    window.setTimeout(() => {
      const assistantMessage: Message = {
        id: messageId + 1,
        role: 'assistant',
        content: 'Your question is ready for the RAG service. Connect VITE_API_BASE_URL when the FastAPI query endpoint is available, and this response can be grounded in your indexed documents.',
        time: currentTime(),
      }
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === conversationId
            ? { ...conversation, messages: [...conversation.messages, assistantMessage] }
            : conversation,
        ),
      )
      setIsThinking(false)
    }, 750)
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    sendMessage()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? 'sidebar--open' : ''}`}>
        <div className="brand-row">
          <div className="brand-mark"><PixelBot small /></div>
          <div>
            <strong>PIXEL MIND</strong>
            <span>KNOWLEDGE BOT</span>
          </div>
          <button className="icon-button close-sidebar" type="button" onClick={() => setSidebarOpen(false)} aria-label="Close menu">×</button>
        </div>

        <button className="new-chat-button" type="button" onClick={startNewChat}>
          <span>＋</span> NEW CHAT
        </button>

        <label className="search-field">
          <span aria-hidden="true">⌕</span>
          <input type="search" placeholder="SEARCH CHATS" aria-label="Search chats" />
          <kbd>/</kbd>
        </label>

        <nav className="conversation-list" aria-label="Conversation history">
          <p className="nav-label">TODAY</p>
          {conversations.slice(0, 3).map((conversation, index) => (
            <button
              className={`conversation-item ${conversation.id === activeId ? 'conversation-item--active' : ''}`}
              type="button"
              key={conversation.id}
              onClick={() => { setActiveId(conversation.id); setSidebarOpen(false) }}
            >
              <span className="chat-pixel" aria-hidden="true">□</span>
              <span>{conversation.title}</span>
              {index === 0 && <i aria-label="Current conversation">●</i>}
            </button>
          ))}

          <p className="nav-label nav-label--spaced">YESTERDAY</p>
          {conversations.slice(3).map((conversation) => (
            <button
              className={`conversation-item ${conversation.id === activeId ? 'conversation-item--active' : ''}`}
              type="button"
              key={conversation.id}
              onClick={() => { setActiveId(conversation.id); setSidebarOpen(false) }}
            >
              <span className="chat-pixel" aria-hidden="true">□</span>
              <span>{conversation.title}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button type="button"><span>?</span> HELP CENTER</button>
          <button type="button"><span>⚙</span> SETTINGS</button>
          <div className="user-card">
            <div className="pixel-avatar" aria-hidden="true">A</div>
            <div><strong>AHMAD</strong><span>LOCAL WORKSPACE</span></div>
            <button type="button" aria-label="Open profile menu">···</button>
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
              <strong>{activeConversation?.title ?? 'NEW CHAT'}</strong>
              <span><i /> SYSTEM ONLINE</span>
            </div>
          </div>
          <div className="topbar-actions">
            <button className="pixel-action" type="button" aria-label="Share conversation">↗</button>
            <button className="pixel-action" type="button" aria-label="More options">•••</button>
          </div>
        </header>

        <section className={`chat-stage ${messages.length ? 'chat-stage--conversation' : ''}`}>
          {messages.length === 0 ? (
            <div className="welcome-state">
              <PixelBot />
              <p className="eyebrow">READY TO SEARCH</p>
              <h1>WHAT CAN I HELP<br />YOU DISCOVER?</h1>
              <p className="intro">Ask a question and I’ll search your knowledge base<br />for the most relevant answer.</p>
              <div className="suggestion-grid">
                {suggestions.map((suggestion) => (
                  <button type="button" key={suggestion.label} onClick={() => sendMessage(suggestion.prompt)}>
                    <span>{suggestion.icon}</span>
                    <strong>{suggestion.label}</strong>
                    <i>↗</i>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="message-list" aria-live="polite">
              {messages.map((message) => (
                <article className={`message message--${message.role}`} key={message.id}>
                  <div className="message-avatar">{message.role === 'assistant' ? <PixelBot small /> : 'A'}</div>
                  <div>
                    <div className="message-meta"><strong>{message.role === 'assistant' ? 'PIXEL MIND' : 'YOU'}</strong><time>{message.time}</time></div>
                    <p>{message.content}</p>
                  </div>
                </article>
              ))}
              {isThinking && (
                <article className="message message--assistant">
                  <div className="message-avatar"><PixelBot small /></div>
                  <div><div className="message-meta"><strong>PIXEL MIND</strong></div><div className="thinking"><i /><i /><i /></div></div>
                </article>
              )}
              <div ref={endRef} />
            </div>
          )}
        </section>

        <div className="composer-wrap">
          <form className="composer" onSubmit={handleSubmit}>
            <button className="attach-button" type="button" aria-label="Attach document">＋</button>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="ASK YOUR KNOWLEDGE BASE..."
              aria-label="Message"
              rows={1}
            />
            <button className="send-button" type="submit" disabled={!input.trim() || isThinking} aria-label="Send message">↑</button>
          </form>
          <p className="composer-note"><span>ENTER</span> TO SEND <b>·</b> <span>SHIFT + ENTER</span> FOR NEW LINE</p>
        </div>
      </main>
    </div>
  )
}

export default App
