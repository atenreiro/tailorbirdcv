import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
// Fonts ship with AutoCV (no Google Fonts request: nothing leaves this computer just to show a page)
import '@fontsource-variable/instrument-sans/wdth.css'
import '@fontsource-variable/instrument-sans/wdth-italic.css'
import '@fontsource/geist-mono/400.css'
import '@fontsource/geist-mono/500.css'
import '@fontsource/geist-mono/600.css'
import './index.css'
import App from './App'

// A data router, so the unsaved-work guard can use useBlocker (in-app links and Back/Forward).
// App keeps its own <Routes>, so the route table lives in one place.
const router = createBrowserRouter([{ path: '*', element: <App /> }])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
