export const generalChat = {
  mode: 'general' as const,
  eyebrow: 'OPEN-DOMAIN CHAT',
  intro: 'Ask anything. Web tools activate when configured.',
  placeholder: 'ASK ANYTHING...',
  suggestions: [
    { icon: '✦', label: 'Explain anything', prompt: 'Explain a useful concept in simple terms.' },
    { icon: '⌁', label: 'Compare options', prompt: 'Help me compare two approaches.' },
    { icon: '◇', label: 'Write some code', prompt: 'Show me a practical code example.' },
    { icon: '↗', label: 'Research the web', prompt: 'Find the latest reliable information about a topic.' },
  ],
}
