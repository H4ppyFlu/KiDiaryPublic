import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { registerSW } from 'virtual:pwa-register'

import App from './App.tsx'
import './index.css'

// Puts `sw.ts` in charge of the app shell (see there). Called without callbacks on
// purpose: a new version waits for the app to be closed rather than announcing itself
// mid-Sitting, so there is nothing here for a Parent to answer. It does nothing in
// `npm run dev`, where there is no built worker to register.
registerSW()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
