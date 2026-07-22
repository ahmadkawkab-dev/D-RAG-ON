import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import ConnectedApp from './ConnectedApp'
import { AppProviders } from '@/components/AppProviders'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppProviders>
      <ConnectedApp />
    </AppProviders>
  </StrictMode>,
)
