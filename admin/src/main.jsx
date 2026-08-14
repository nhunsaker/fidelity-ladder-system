// Entry — SorbProvider wraps the app: the Sorb pipeline delivers the Primer token set as
// CSS custom properties; every component reads var(--token, fallback). PreviewBanner renders
// nothing outside a live preview session (the Figma-plugin re-skin beat).
import { PreviewBanner, SorbProvider } from '@sorb/leaf'
import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { sorbConfig } from './sorbConfig.js'
import './tokens/generated/variables.css'
import './app.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <SorbProvider config={sorbConfig}>
      <App />
      <PreviewBanner />
    </SorbProvider>
  </React.StrictMode>,
)
