import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { APP_NAME } from '../shared/app'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <div>{APP_NAME}</div>
  </StrictMode>
)
