import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { motion, useAnimationControls } from 'motion/react'
import { toast } from 'sonner'
import {
  Archive,
  BookOpenText,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Globe2,
  LoaderCircle,
  LogOut,
  MessageSquareText,
  Network,
  Paperclip,
  Plus,
  RotateCcw,
  Search,
  Send,
  Settings,
  Sparkles,
  Trash2,
} from 'lucide-react'
import {
  ApiError,
  AuthenticationError,
  deleteSession,
  getSession,
  restoreSession,
  logout,
  listSessions,
  selectGeneralAnswer,
  streamChat,
} from './api/client'
import type {
  AnswerId,
  AuthSession,
  ChatMessage,
  ChatMode,
  ChatSession,
  DualAnswerCandidate,
  DualAnswerGeneration,
  Feedback,
} from './api/types'
import { AuthPanel } from './components/AuthPanel'
import { BubbleBackground } from './components/animate-ui/components/backgrounds/bubble'
import { ConversationExportMenu } from './components/ConversationExportMenu'
import { DualAnswerRenderer } from './DualAnswerRenderer'
import { FeedbackControls } from './components/FeedbackControls'
import { HighlightedResponseRenderer as ResponseRenderer } from './components/HighlightedResponseRenderer'
import { ModeToggle } from './components/mode-toggle'
import { OnboardingGuide } from './components/OnboardingGuide'
import { PixelBot } from './components/PixelBot'
import { ProfileSettings } from './components/ProfileSettings'
import { Alert, AlertDescription } from './components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from './components/ui/alert-dialog'
import { Avatar, AvatarFallback, AvatarImage } from './components/ui/avatar'
import { Badge } from './components/ui/badge'
import { Button } from './components/ui/button'
import { Card, CardContent } from './components/ui/card'
import { ScrollArea } from './components/ui/scroll-area'
import { Separator } from './components/ui/separator'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarInput,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from './components/ui/sidebar'
import { Skeleton } from './components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from './components/ui/tabs'
import { Textarea } from './components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from './components/ui/tooltip'
import { documentChat } from './features/DocumentChat'
import { generalChat } from './features/GeneralChat'

type UiMessage = ChatMessage

const modeDefinition = (mode: ChatMode) => mode === 'general' ? generalChat : documentChat
const suggestionIcons = [Sparkles, Network, BookOpenText, Globe2]
const bubbleTypingColors = [
  '129,140,248',
  '34,211,238',
  '167,139,250',
  '244,114,182',
  '45,212,191',
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
  if (error instanceof TypeError) return 'Unable to reach the API. Check that the .NET API is running and the API URL is correct.'
  return 'Something went wrong while contacting the API.'
}

function BubbleAmbience({
  compact,
  pulse,
  onNewChat,
}: {
  compact: boolean
  pulse: number
  onNewChat: () => void
}) {
  const controls = useAnimationControls()
  const typingColor = bubbleTypingColors[pulse % bubbleTypingColors.length]

  useEffect(() => {
    if (!pulse) return
    void controls.start({
      scale: [1, 1.035, 1],
      rotate: [0, pulse % 2 === 0 ? 0.45 : -0.45, 0],
      transition: { duration: 0.32, ease: 'easeOut' },
    })
  }, [controls, pulse])

  return (
    <motion.button
      type="button"
      animate={controls}
      onClick={onNewChat}
      tabIndex={compact ? 0 : -1}
      aria-label="Start a new chat"
      title="Start a new chat"
      className={compact
        ? 'absolute right-4 top-4 z-20 h-12 w-20 overflow-hidden rounded-xl border border-primary/20 p-0 opacity-40 shadow-lg transition-opacity duration-300 hover:opacity-75 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring md:right-8 md:h-20 md:w-32'
        : 'absolute inset-0 z-0 overflow-hidden border-0 p-0 text-left'}
    >
      <BubbleBackground
        interactive
        className="absolute inset-0 bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900"
        colors={{
          first: '99,102,241',
          second: '56,189,248',
          third: '139,92,246',
          fourth: '30,64,175',
          fifth: '71,85,105',
          sixth: typingColor,
        }}
      />
      {!compact && <div className="absolute inset-0 bg-background/35 dark:bg-background/45" />}
    </motion.button>
  )
}

type ChatSidebarProps = {
  auth: AuthSession
  mode: ChatMode
  search: string
  historyLoading: boolean
  todaySessions: ChatSession[]
  earlierSessions: ChatSession[]
  activeId: string | null
  runningSessionId: string | null
  initials: string
  onSearchChange: (value: string) => void
  onModeChange: (mode: ChatMode) => void
  onNewChat: () => void
  onOpenSession: (sessionId: string) => void
  onAuthChange: (auth: AuthSession) => void
  onOpenGuide: () => void
  onSignOut: () => void
}

function ChatSidebar({
  auth,
  mode,
  search,
  historyLoading,
  todaySessions,
  earlierSessions,
  activeId,
  runningSessionId,
  initials,
  onSearchChange,
  onModeChange,
  onNewChat,
  onOpenSession,
  onAuthChange,
  onOpenGuide,
  onSignOut,
}: ChatSidebarProps) {
  const { setOpenMobile } = useSidebar()
  const sessionCount = todaySessions.length + earlierSessions.length

  const closeAfter = (action: () => void) => {
    action()
    setOpenMobile(false)
  }

  const renderSessionGroup = (label: string, group: ChatSession[]) => {
    if (!group.length) return null
    return (
      <SidebarGroup>
        <SidebarGroupLabel>{label}</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            {group.map((session) => (
              <SidebarMenuItem key={session.id}>
                <SidebarMenuButton
                  type="button"
                  isActive={session.id === activeId}
                  tooltip={session.title}
                  onClick={() => closeAfter(() => onOpenSession(session.id))}
                >
                  <MessageSquareText aria-hidden="true" />
                  <span>{session.title}</span>
                </SidebarMenuButton>
                {(session.id === activeId || session.id === runningSessionId) && (
                  <SidebarMenuBadge aria-label={session.id === runningSessionId ? 'Answer running' : 'Current conversation'}>
                    {session.id === runningSessionId
                      ? <LoaderCircle className="size-3 animate-spin" aria-hidden="true" />
                      : <span className="size-1.5 rounded-full bg-primary" />}
                  </SidebarMenuBadge>
                )}
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    )
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="gap-3 border-b p-3">
        <div className="flex items-center gap-3 px-1">
          <PixelBot small />
          <div className="min-w-0 group-data-[collapsible=icon]:hidden">
            <p className="truncate text-sm font-semibold">Pixel Mind</p>
            <p className="truncate text-xs text-muted-foreground">Knowledge assistant</p>
          </div>
        </div>
        <Button
          type="button"
          onClick={() => closeAfter(onNewChat)}
          className="w-full justify-start group-data-[collapsible=icon]:size-8 group-data-[collapsible=icon]:p-0"
        >
          <Plus aria-hidden="true" />
          <span className="group-data-[collapsible=icon]:hidden">New chat</span>
        </Button>
        <Tabs
          value={mode}
          onValueChange={(value) => closeAfter(() => onModeChange(value as ChatMode))}
          className="group-data-[collapsible=icon]:hidden"
        >
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="general">General</TabsTrigger>
            <TabsTrigger value="document">Documents</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="relative group-data-[collapsible=icon]:hidden">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 z-10 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <SidebarInput
            type="search"
            placeholder="Search chats"
            aria-label="Search chats"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            className="pl-8"
          />
        </div>
      </SidebarHeader>

      <SidebarContent>
        <ScrollArea className="h-full">
          {historyLoading && !sessionCount ? (
            <SidebarGroup>
              <SidebarGroupLabel>Loading history</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {Array.from({ length: 4 }).map((_, index) => <SidebarMenuSkeleton key={index} showIcon />)}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ) : null}
          {!historyLoading && !sessionCount ? (
            <div className="m-3 rounded-lg border border-dashed p-4 text-center group-data-[collapsible=icon]:hidden">
              <Archive className="mx-auto mb-2 size-5 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm font-medium">No saved chats</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {search ? 'Try a different search.' : 'Your conversations will appear here.'}
              </p>
            </div>
          ) : null}
          {renderSessionGroup('Today', todaySessions)}
          {renderSessionGroup('Earlier', earlierSessions)}
        </ScrollArea>
      </SidebarContent>

      <SidebarFooter className="border-t p-2">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              type="button"
              tooltip="Help center"
              onClick={() => closeAfter(onOpenGuide)}
            >
              <CircleHelp aria-hidden="true" />
              <span>Help center</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <ProfileSettings auth={auth} onAuthChange={onAuthChange}>
              <SidebarMenuButton type="button" tooltip="Settings">
                <Settings aria-hidden="true" />
                <span>Settings</span>
              </SidebarMenuButton>
            </ProfileSettings>
          </SidebarMenuItem>
        </SidebarMenu>
        <Separator className="my-1" />
        <div className="flex items-center gap-2 rounded-lg p-1">
          <Avatar className="size-8">
            {auth.avatarUrl && <AvatarImage src={auth.avatarUrl} alt="" />}
            <AvatarFallback className="bg-primary text-xs text-primary-foreground">{initials}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
            <p className="truncate text-sm font-medium">{auth.fullName}</p>
            <p className="truncate text-xs text-muted-foreground">{auth.email}</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={onSignOut}
            aria-label="Sign out"
            className="group-data-[collapsible=icon]:hidden"
          >
            <LogOut aria-hidden="true" />
          </Button>
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}

function ConnectedApp() {
  const [auth, setAuth] = useState<AuthSession | null>(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [mode, setMode] = useState<ChatMode>('document')
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<UiMessage[]>([])
  const [input, setInput] = useState('')
  const [search, setSearch] = useState('')
  const [isThinking, setIsThinking] = useState(false)
  const [runningSessionId, setRunningSessionId] = useState<string | null>(null)
  const [historyLoading, setHistoryLoading] = useState(Boolean(auth))
  const [error, setError] = useState('')
  const [selectedVersions, setSelectedVersions] = useState<Record<string, number>>({})
  const [hasNewContent, setHasNewContent] = useState(false)
  const [bubblePulse, setBubblePulse] = useState(0)
  const [dualAnswers, setDualAnswers] = useState<Record<string, DualAnswerGeneration>>({})
  const [guideOpen, setGuideOpen] = useState(false)
  const stageRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const endRef = useRef<HTMLDivElement>(null)
  const streamController = useRef<AbortController | null>(null)
  const activeIdRef = useRef<string | null>(null)
  const backgroundMessages = useRef(new Map<string, UiMessage[]>())
  const currentMode = modeDefinition(mode)
  const onboardingStorageKey = auth
    ? `pixel-mind:onboarding:v1:${auth.email}`
    : 'pixel-mind:onboarding:v1'
  const hasPendingChoice = Object.values(dualAnswers).some(
    (generation) => generation.selectedAnswerId === null,
  )

  const latestVersionByReply = new Map<string, number>()
  for (const message of messages) {
    if (message.role === 'assistant' && message.reply_to_message_id) {
      latestVersionByReply.set(
        message.reply_to_message_id,
        Math.max(latestVersionByReply.get(message.reply_to_message_id) ?? 0, message.version),
      )
    }
  }
  const visibleMessages = messages.filter((message) => {
    if (message.role !== 'assistant' || !message.reply_to_message_id) return true
    const selected = selectedVersions[message.reply_to_message_id]
      ?? latestVersionByReply.get(message.reply_to_message_id)
    return message.version === selected
  })
  const versionsFor = (message: UiMessage) => message.reply_to_message_id
    ? messages
      .filter((candidate) => candidate.role === 'assistant' && candidate.reply_to_message_id === message.reply_to_message_id)
      .sort((a, b) => a.version - b.version)
    : [message]
  const activeSession = sessions.find((session) => session.id === activeId)
  const filteredSessions = sessions.filter((session) => session.title.toLowerCase().includes(search.trim().toLowerCase()))
  const todaySessions = filteredSessions.filter((session) => isToday(session.updated_at))
  const earlierSessions = filteredSessions.filter((session) => !isToday(session.updated_at))

  useEffect(() => {
    let cancelled = false
    restoreSession()
      .then((session) => { if (!cancelled) setAuth(session) })
      .catch(() => { if (!cancelled) setAuth(null) })
      .finally(() => { if (!cancelled) setAuthLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!auth) return

    if (window.localStorage.getItem(onboardingStorageKey) !== 'completed') {
      setGuideOpen(true)
    }
  }, [auth, onboardingStorageKey])

  useEffect(() => {
    if (!auth) return
    let cancelled = false
    listSessions(mode)
      .then((value) => { if (!cancelled) setSessions(value) })
      .catch((caught) => {
        if (cancelled) return
        if (caught instanceof AuthenticationError) {
          void logout()
          setAuth(null)
        }
        setError(readableError(caught))
      })
      .finally(() => { if (!cancelled) setHistoryLoading(false) })
    return () => { cancelled = true }
  }, [auth, mode])

  useEffect(() => {
    if (stickToBottomRef.current) {
      endRef.current?.scrollIntoView({ behavior: 'smooth' })
    } else if (isThinking) {
      queueMicrotask(() => setHasNewContent(true))
    }
  }, [messages, isThinking])

  useEffect(() => () => streamController.current?.abort(), [])
  useEffect(() => {
    activeIdRef.current = activeId
  }, [activeId])

  const handleStageScroll = () => {
    const stage = stageRef.current
    if (!stage) return
    const nearBottom = stage.scrollHeight - stage.scrollTop - stage.clientHeight < 96
    stickToBottomRef.current = nearBottom
    if (nearBottom) setHasNewContent(false)
  }

  const jumpToLatest = () => {
    stickToBottomRef.current = true
    setHasNewContent(false)
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  if (authLoading) return <AuthPanel loading />
  if (!auth) return <AuthPanel />

  const handleApiError = (caught: unknown, title = 'Request failed') => {
    if (caught instanceof AuthenticationError) {
      void logout()
      setAuth(null)
    }
    const message = readableError(caught)
    if (message) {
      setError(message)
      toast.error(title, {
        description: message,
        duration: 12_000,
      })
    }
  }

  const handleFeedback = (messageId: string, feedback: Feedback) => {
    setMessages((current) => current.map((message) =>
      message.id === messageId ? { ...message, feedback } : message))
    if (activeId) {
      const buffered = backgroundMessages.current.get(activeId)
      if (buffered) {
        backgroundMessages.current.set(activeId, buffered.map((message) =>
          message.id === messageId ? { ...message, feedback } : message))
      }
    }
  }

  const refreshSessionList = async () => {
    setSessions(await listSessions(mode))
  }

  const switchMode = (nextMode: ChatMode) => {
    if (nextMode === mode) return
    setMode(nextMode)
    setSessions([])
    setActiveId(null)
    activeIdRef.current = null
    setMessages([])
    setDualAnswers({})
    setInput('')
    setError('')
    setHistoryLoading(true)
  }

  const startNewChat = () => {
    setActiveId(null)
    setMessages([])
    setDualAnswers({})
    activeIdRef.current = null
    setInput('')
    setError('')
  }

  const openSession = async (sessionId: string) => {
    if (sessionId === activeId) return
    setError('')
    setDualAnswers({})
    setHistoryLoading(true)
    const buffered = backgroundMessages.current.get(sessionId)
    if (buffered) {
      activeIdRef.current = sessionId
      setActiveId(sessionId)
      setMessages(buffered)
      setHistoryLoading(false)
      return
    }
    try {
      const detail = await getSession(sessionId)
      setActiveId(sessionId)
      activeIdRef.current = sessionId
      setMessages(detail.messages)
    } catch (caught) {
      handleApiError(caught)
    } finally {
      setHistoryLoading(false)
    }
  }

  const removeActiveSession = async () => {
    if (!activeId || isThinking) return
    try {
      await deleteSession(activeId)
      setActiveId(null)
      setMessages([])
      setDualAnswers({})
      await refreshSessionList()
    } catch (caught) {
      handleApiError(caught)
    }
  }

  const signOut = () => {
    streamController.current?.abort()
    void logout()
    setAuth(null)
    setSessions([])
    backgroundMessages.current.clear()
    setMessages([])
    setDualAnswers({})
    setActiveId(null)
    activeIdRef.current = null
  }

  const selectDualAnswer = async (
    placeholderMessageId: string,
    generationId: string,
    answerId: AnswerId,
  ): Promise<void> => {
    const generation = dualAnswers[placeholderMessageId]
    const placeholderMessage = messages.find(
      (message) => message.id === placeholderMessageId,
    )

    if (!generation || generation.selectedAnswerId) return

    const sessionId = placeholderMessage?.session_id || activeId
    const replyToMessageId = placeholderMessage?.reply_to_message_id

    if (!sessionId || !replyToMessageId) {
      throw new ApiError(
        'The pending answer is missing its session or user-message identifier.',
      )
    }

    setDualAnswers((current) => {
      const existing = current[placeholderMessageId]
      if (!existing) return current

      return {
        ...current,
        [placeholderMessageId]: {
          ...existing,
          selectedAnswerId: answerId,
        },
      }
    })

    try {
      const selected = await selectGeneralAnswer(
        sessionId,
        replyToMessageId,
        generationId,
        answerId,
      )

      setMessages((current) => current.map((message) =>
        message.id === placeholderMessageId
          ? {
              ...message,
              id: selected.id,
              session_id: selected.session_id,
              content: selected.content,
              sources: selected.sources,
              timestamp: selected.timestamp,
              reply_to_message_id: selected.reply_to_message_id,
              version: selected.version,
              feedback: selected.feedback,
              pending: false,
            }
          : message))

      setDualAnswers((current) => {
        const next = { ...current }
        delete next[placeholderMessageId]
        return next
      })

      const [detail, updatedSessions] = await Promise.all([
        getSession(selected.session_id),
        listSessions('general'),
      ])

      backgroundMessages.current.delete(selected.session_id)
      if (activeIdRef.current === selected.session_id) {
        setMessages(detail.messages)
      }
      setSessions(updatedSessions)
      toast.success('Answer selected')
    } catch (caught) {
      setDualAnswers((current) => {
        const existing = current[placeholderMessageId]
        if (!existing) return current
        return {
          ...current,
          [placeholderMessageId]: {
            ...existing,
            selectedAnswerId: null,
          },
        }
      })
      throw caught
    }
  }

  const sendMessage = async (rawInput = input, regenerateMessageId?: string) => {
    const content = rawInput.trim()
    if (!content || isThinking || hasPendingChoice) return

    const originSessionId = activeId
    let taskSessionId = activeId
    const taskMode = mode
    const requestId = crypto.randomUUID()
    const now = new Date().toISOString()
    const userMessage: UiMessage = {
      id: requestId + '-user', session_id: activeId ?? '', role: 'user', content, sources: [], timestamp: now,
      reply_to_message_id: null, version: 1, feedback: null,
    }
    const assistantMessage: UiMessage = {
      id: requestId + '-assistant', session_id: activeId ?? '', role: 'assistant', content: '', sources: [], timestamp: now, pending: true,
      reply_to_message_id: regenerateMessageId ?? null, version: 1, feedback: null,
    }
    let taskMessages = regenerateMessageId
      ? [...messages, assistantMessage]
      : [...messages, userMessage, assistantMessage]

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
    let dualGenerationSeen = false

    const updateDualCandidate = (
      generationId: string,
      answerId: AnswerId,
      update: (
        candidate: DualAnswerCandidate,
      ) => DualAnswerCandidate,
      label: string = answerId,
    ): void => {
      setDualAnswers((current) => {
        const existing: DualAnswerGeneration =
          current[assistantMessage.id] ?? {
            generationId,
            answers: [],
            sources: [],
            selectedAnswerId: null,
            completed: false,
          }

        const candidate: DualAnswerCandidate =
          existing.answers.find(
            (answer) => answer.id === answerId,
          ) ?? {
            id: answerId,
            label,
            content: '',
            completed: false,
          }
        const answers = existing.answers.some((answer) => answer.id === answerId)
          ? existing.answers.map((answer) => answer.id === answerId ? update(answer) : answer)
          : [...existing.answers, update(candidate)]
        return {
          ...current,
          [assistantMessage.id]: {
            ...existing,
            generationId,
            answers,
          },
        }
      })
    }

    try {
      await streamChat(taskMode, content, activeId, {
        onStarted: (event) => {
          const { sessionId } = event
          const previousTaskId = taskSessionId
          taskSessionId = sessionId
          taskMessages = taskMessages.map((message) => message.id === assistantMessage.id
            ? { ...message, session_id: sessionId, reply_to_message_id: event.replyToMessageId, version: event.version }
            : { ...message, session_id: sessionId })
          if (event.replyToMessageId) {
            setSelectedVersions((current) => ({ ...current, [event.replyToMessageId]: event.version }))
          }
          if (previousTaskId && previousTaskId !== sessionId) {
            backgroundMessages.current.delete(previousTaskId)
          }
          backgroundMessages.current.set(sessionId, taskMessages)
          setRunningSessionId(sessionId)
          setSessions((current) => current.some((session) => session.id === sessionId)
            ? current
            : [{
                id: sessionId,
                title: content.length > 48 ? content.slice(0, 48) + '...' : content,
                mode: taskMode,
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
        onGenerationStarted: (event) => {
          if (event.answerCount <= 1) return

          dualGenerationSeen = true
          setDualAnswers((current) => ({
            ...current,
            [assistantMessage.id]: {
              generationId: event.generationId,
              answers: [],
              sources: event.sources,
              selectedAnswerId: null,
              completed: false,
            },
          }))
          if (event.sources.length) {
            updateTaskMessages((current) => current.map((message) =>
              message.id === assistantMessage.id
                ? { ...message, sources: event.sources }
                : message))
          }
        },
        onAnswerStarted: (event) => {
          updateDualCandidate(
            event.generationId,
            event.answerId,
            (candidate) => ({ ...candidate, label: event.label }),
            event.label,
          )
        },
        onAnswerDelta: (event) => {
          updateDualCandidate(
            event.generationId,
            event.answerId,
            (candidate) => ({
              ...candidate,
              label: event.label,
              content: candidate.content + event.content,
            }),
            event.label,
          )
        },
        onAnswerDone: (event) => {
          updateDualCandidate(
            event.generationId,
            event.answerId,
            (candidate) => ({ ...candidate, completed: true }),
          )
        },
        onAnswerError: (event) => {
          updateDualCandidate(
            event.generationId,
            event.answerId,
            (candidate) => ({
              ...candidate,
              label: event.label,
              completed: true,
              error: event.error,
            }),
            event.label,
          )
        },
        onGenerationDone: (event) => {
          dualGenerationSeen = true
          setDualAnswers((current) => {
            const existing = current[assistantMessage.id]
            if (!existing) return current
            return {
              ...current,
              [assistantMessage.id]: {
                ...existing,
                generationId: event.generationId,
                completed: true,
              },
            }
          })
          updateTaskMessages((current) => current.map((message) =>
            message.id === assistantMessage.id
              ? { ...message, pending: false }
              : message))
        },
        onDone: (event) => {
          completedSessionId = event.sessionId
          if (event.replyToMessageId) {
            setSelectedVersions((current) => ({ ...current, [event.replyToMessageId]: event.version }))
          }
        },
      }, { regenerateMessageId, signal: controller.signal })

      if (dualGenerationSeen) {
        toast.info('Choose an answer', {
          description: 'Select one response to continue this conversation.',
        })
        return
      }

      if (!completedSessionId) throw new ApiError('The API did not return a session identifier')
      const [detail, updatedSessions] = await Promise.all([
        getSession(completedSessionId),
        listSessions(taskMode),
      ])
      backgroundMessages.current.delete(completedSessionId)
      if (activeIdRef.current === completedSessionId) setMessages(detail.messages)
      setSessions(updatedSessions)
      toast.success('Answer ready', {
        description: 'The full response has finished generating.',
      })
    } catch (caught) {
      updateTaskMessages((current) => current
        .filter((message) => message.id !== assistantMessage.id || message.content.length > 0)
        .map((message) => ({ ...message, pending: false })))
      const detail = readableError(caught)
      const title = /timed out/i.test(detail)
        ? 'Answer timed out'
        : /incomplete|before completion|unable to complete/i.test(detail)
          ? 'Answer incomplete'
          : 'Answer generation failed'
      handleApiError(caught, title)
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

  const handleWorkspaceKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key.length === 1 || ['Enter', 'Backspace', 'Delete'].includes(event.key)) {
      setBubblePulse((current) => current + 1)
    }
  }

  const initials = auth.fullName.trim().slice(0, 1).toUpperCase() || 'U'

  return (
    <SidebarProvider defaultOpen>
      <div className="flex h-svh w-full overflow-hidden" onKeyDownCapture={handleWorkspaceKeyDown}>
        <ChatSidebar
          auth={auth}
          mode={mode}
          search={search}
          historyLoading={historyLoading}
          todaySessions={todaySessions}
          earlierSessions={earlierSessions}
          activeId={activeId}
          runningSessionId={runningSessionId}
          initials={initials}
          onSearchChange={setSearch}
          onModeChange={switchMode}
          onNewChat={startNewChat}
          onOpenSession={(sessionId) => void openSession(sessionId)}
          onAuthChange={setAuth}
          onOpenGuide={() => setGuideOpen(true)}
          onSignOut={signOut}
        />

        <SidebarInset className="min-w-0 overflow-hidden">
          <header className="flex h-16 shrink-0 items-center gap-3 border-b bg-background/90 px-3 backdrop-blur md:px-5">
            <SidebarTrigger />
            <Separator orientation="vertical" className="h-5" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h1 className="truncate text-sm font-semibold md:text-base">{activeSession?.title ?? 'New chat'}</h1>
                <Badge variant="outline" className="hidden shrink-0 sm:inline-flex">
                  {mode === 'document' ? 'Documents' : 'General'}
                </Badge>
              </div>
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                {isThinking ? (
                  <>
                    <LoaderCircle className="size-3 animate-spin text-primary" aria-hidden="true" />
                    Answer running in background
                  </>
                ) : historyLoading ? (
                  <>
                    <LoaderCircle className="size-3 animate-spin" aria-hidden="true" />
                    Syncing
                  </>
                ) : (
                  <>
                    <span className="size-1.5 rounded-full bg-emerald-500" />
                    System online
                  </>
                )}
              </p>
            </div>

            <div className="flex items-center gap-1">
              <ConversationExportMenu
                title={activeSession?.title ?? 'Conversation'}
                messages={visibleMessages}
                disabled={!activeId || visibleMessages.length === 0}
              />
              <ModeToggle />
              <AlertDialog>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <AlertDialogTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        disabled={!activeId || isThinking}
                        aria-label="Delete conversation"
                      >
                        <Trash2 aria-hidden="true" />
                      </Button>
                    </AlertDialogTrigger>
                  </TooltipTrigger>
                  <TooltipContent>Delete conversation</TooltipContent>
                </Tooltip>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This permanently deletes the conversation and all of its messages.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction variant="destructive" onClick={() => void removeActiveSession()}>
                      Delete conversation
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button type="button" variant="ghost" size="icon" onClick={signOut} aria-label="Sign out">
                    <LogOut aria-hidden="true" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Sign out</TooltipContent>
              </Tooltip>
            </div>
          </header>

          <section className="relative min-h-0 flex-1 overflow-hidden bg-background">
            <BubbleAmbience compact={messages.length > 0} pulse={bubblePulse} onNewChat={startNewChat} />
            <div
              ref={stageRef}
              onScroll={handleStageScroll}
              className="relative z-10 h-full overflow-y-auto overscroll-contain"
            >
              {messages.length === 0 ? (
                <div className="flex min-h-full items-center justify-center p-4 py-12 md:p-8">
                  <div className="relative z-10 w-full max-w-4xl">
                    <Card className="border-white/20 bg-background/80 shadow-2xl backdrop-blur-xl">
                      <CardContent className="space-y-7 p-6 text-center sm:p-10">
                        <div className="space-y-3">
                          <Badge variant="secondary">{currentMode.eyebrow}</Badge>
                          <h2 className="text-balance text-3xl font-semibold tracking-tight sm:text-5xl">
                            What can I help you discover?
                          </h2>
                          <p className="mx-auto max-w-2xl text-pretty text-sm leading-6 text-muted-foreground sm:text-base">
                            {currentMode.intro}
                          </p>
                        </div>
                        {error && (
                          <Alert variant="destructive" role="alert" className="text-left">
                            <AlertDescription>{error}</AlertDescription>
                          </Alert>
                        )}
                        <div className="grid gap-3 text-left sm:grid-cols-2">
                          {currentMode.suggestions.map((suggestion, index) => {
                            const SuggestionIcon = suggestionIcons[index % suggestionIcons.length]
                            return (
                              <Button
                                type="button"
                                key={suggestion.label}
                                variant="outline"
                                disabled={isThinking}
                                onClick={() => void sendMessage(suggestion.prompt)}
                                className="h-auto justify-start gap-3 bg-background/75 p-4 text-left"
                              >
                                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                                  <SuggestionIcon className="size-4" aria-hidden="true" />
                                </span>
                                <span className="min-w-0 flex-1">
                                  <span className="block font-medium">{suggestion.label}</span>
                                  <span className="mt-0.5 block truncate text-xs font-normal text-muted-foreground">
                                    {suggestion.prompt}
                                  </span>
                                </span>
                                <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                              </Button>
                            )
                          })}
                        </div>
                      </CardContent>
                    </Card>
                  </div>
                </div>
              ) : (
                <div className="relative mx-auto w-full max-w-4xl space-y-8 px-4 pb-8 pt-20 sm:px-6 md:pt-28" aria-live="polite">
                  {error && (
                    <Alert variant="destructive" role="alert">
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}
                  {visibleMessages.map((message) => {
                    const versions = versionsFor(message)
                    const dualGeneration = dualAnswers[message.id]
                    return (
                      <article
                        key={message.id}
                        aria-busy={Boolean(message.pending)}
                        className={message.role === 'user'
                          ? 'ml-auto flex max-w-3xl flex-row-reverse gap-3'
                          : dualGeneration
                            ? 'flex max-w-4xl gap-3'
                            : 'flex max-w-3xl gap-3'}
                      >
                        <Avatar className="mt-0.5 size-8 border shadow-sm">
                          {message.role === 'user' && auth.avatarUrl && <AvatarImage src={auth.avatarUrl} alt="" />}
                          <AvatarFallback className={message.role === 'assistant'
                            ? 'bg-primary p-0 text-primary-foreground'
                            : 'bg-secondary text-secondary-foreground'}>
                            {message.role === 'assistant' ? <PixelBot small /> : initials}
                          </AvatarFallback>
                        </Avatar>
                        <div className={message.role === 'user' ? 'min-w-0 text-right' : 'min-w-0 flex-1'}>
                          <div className={message.role === 'user'
                            ? 'mb-1.5 flex flex-row-reverse items-center gap-2'
                            : 'mb-1.5 flex items-center gap-2'}>
                            <strong className="text-xs font-semibold">
                              {message.role === 'assistant' ? 'Pixel Mind' : 'You'}
                            </strong>
                            <time className="text-xs text-muted-foreground">{timestamp(message.timestamp)}</time>
                          </div>
                          <div className={message.role === 'user'
                            ? 'inline-block rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-left text-sm leading-6 text-primary-foreground shadow-sm'
                            : 'rounded-2xl rounded-tl-sm border bg-card p-4 text-left shadow-sm sm:p-5'}>
                            {message.role === 'assistant' && dualGeneration ? (
                              <DualAnswerRenderer
                                generationId={dualGeneration.generationId}
                                answers={dualGeneration.answers}
                                sources={dualGeneration.sources.length
                                  ? dualGeneration.sources
                                  : message.sources}
                                selectedAnswerId={dualGeneration.selectedAnswerId}
                                onSelect={(
                                  generationId: string,
                                  answerId: AnswerId,
                                ) =>
                                  selectDualAnswer(
                                    message.id,
                                    generationId,
                                    answerId,
                                  )}
                              />
                            ) : message.content ? (
                              message.role === 'assistant' ? (
                                <ResponseRenderer content={message.content} sources={message.sources} />
                              ) : (
                                <p className="whitespace-pre-wrap">{message.content}</p>
                              )
                            ) : message.pending ? (
                              <div className="w-full min-w-56 space-y-2" aria-label="Generating response">
                                <Skeleton className="h-4 w-[92%]" />
                                <Skeleton className="h-4 w-[78%]" />
                                <Skeleton className="h-4 w-[56%]" />
                              </div>
                            ) : null}
                          </div>
                          {message.role === 'assistant' && message.content && !message.pending && !dualGeneration ? (
                            <FeedbackControls
                              message={message}
                              onSaved={(feedback) => handleFeedback(message.id, feedback)}
                            />
                          ) : null}
                          {message.role === 'assistant' && message.reply_to_message_id && !message.pending && !dualGeneration ? (
                            <div className="mt-3 flex flex-wrap items-center gap-1">
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                disabled={message.version <= versions[0].version}
                                onClick={() => setSelectedVersions((current) => ({
                                  ...current,
                                  [message.reply_to_message_id!]: message.version - 1,
                                }))}
                                aria-label="Previous answer version"
                              >
                                <ChevronLeft aria-hidden="true" />
                              </Button>
                              <span className="px-1 text-xs text-muted-foreground">
                                Version {message.version} of {versions.length}
                              </span>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                disabled={message.version >= versions.at(-1)!.version}
                                onClick={() => setSelectedVersions((current) => ({
                                  ...current,
                                  [message.reply_to_message_id!]: message.version + 1,
                                }))}
                                aria-label="Next answer version"
                              >
                                <ChevronRight aria-hidden="true" />
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={isThinking}
                                onClick={() => {
                                  const prompt = messages.find((candidate) => candidate.id === message.reply_to_message_id)
                                  if (prompt) void sendMessage(prompt.content, prompt.id)
                                }}
                              >
                                <RotateCcw aria-hidden="true" />
                                Regenerate
                              </Button>
                            </div>
                          ) : null}
                        </div>
                      </article>
                    )
                  })}
                  <div ref={endRef} />
                </div>
              )}
            </div>

            {hasNewContent && (
              <Button
                type="button"
                size="sm"
                onClick={jumpToLatest}
                className="absolute bottom-4 left-1/2 z-30 -translate-x-1/2 rounded-full shadow-lg"
              >
                New content <ChevronDown aria-hidden="true" />
              </Button>
            )}
          </section>

          <div className="shrink-0 border-t bg-background/95 px-3 py-3 backdrop-blur md:px-6">
            <form className="mx-auto flex max-w-4xl items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm" onSubmit={handleSubmit}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button type="button" variant="ghost" size="icon" aria-label="Attach document" className="shrink-0">
                    <Paperclip aria-hidden="true" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Document upload is planned for a future release</TooltipContent>
              </Tooltip>
              <Textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={hasPendingChoice
                  ? 'Choose one of the answers above to continue'
                  : currentMode.placeholder}
                aria-label="Message"
                rows={1}
                disabled={isThinking || hasPendingChoice}
                className="max-h-40 min-h-10 resize-none border-0 bg-transparent px-2 py-2.5 shadow-none focus-visible:ring-0"
              />
              <Button
                type="submit"
                size="icon"
                disabled={!input.trim() || isThinking || hasPendingChoice}
                aria-label="Send message"
                className="shrink-0 rounded-xl"
              >
                {isThinking ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Send aria-hidden="true" />}
              </Button>
            </form>
            <p className="mx-auto mt-2 max-w-4xl text-center text-[11px] text-muted-foreground">
              {hasPendingChoice
                ? 'Choose one answer above before sending the next message.'
                : 'Enter to send. Shift + Enter for a new line.'}
            </p>
          </div>
        </SidebarInset>
      </div>

      <OnboardingGuide
        open={guideOpen}
        storageKey={onboardingStorageKey}
        onOpenChange={setGuideOpen}
      />
    </SidebarProvider>
  )
}

export default ConnectedApp