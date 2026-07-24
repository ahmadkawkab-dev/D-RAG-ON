export const documentChat = {
  mode: 'document' as const,
  eyebrow: 'READY TO SEARCH',
  intro: 'Ask a question and I’ll search your knowledge base for the most relevant answer.',
  placeholder: 'ASK YOUR KNOWLEDGE BASE...',
  suggestions: [
    { icon: '✦', label: 'Summarize a document', prompt: 'Summarize the key ideas in my knowledge base.' },
    { icon: '⌁', label: 'Find a connection', prompt: 'Find connections between the documents in my knowledge base.' },
    { icon: '◇', label: 'Explain a concept', prompt: 'Explain the most important concept in simple terms.' },
    { icon: '↗', label: 'Draft from sources', prompt: 'Draft a short brief using my indexed sources.' },
  ],
}
