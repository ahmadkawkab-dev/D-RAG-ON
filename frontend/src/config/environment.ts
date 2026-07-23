const DEFAULT_API_BASE_URL = 'https://localhost:7187'

function resolveApiBaseUrl(value: string | undefined): string {
  const candidate = value?.trim() || DEFAULT_API_BASE_URL

  try {
    const url = new URL(candidate)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      throw new Error('The API URL must use HTTP or HTTPS.')
    }
    if (url.username || url.password) {
      throw new Error('The API URL must not contain credentials.')
    }
    return url.toString().replace(/\/$/, '')
  } catch (error) {
    const detail = error instanceof Error ? error.message : 'Invalid URL.'
    throw new Error(`Invalid VITE_API_BASE_URL: ${detail}`)
  }
}

export const apiBaseUrl = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL)
