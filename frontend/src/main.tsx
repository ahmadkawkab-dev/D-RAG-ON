import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import ConnectedApp from './ConnectedApp'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import { AppProviders } from '@/components/AppProviders'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppProviders>
      <AppErrorBoundary>
        <ConnectedApp />
      </AppErrorBoundary>
    </AppProviders>
  </StrictMode>,
)
