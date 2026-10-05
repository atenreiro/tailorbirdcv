import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // The UI is served from the user's own computer, never over a slow network: one ~560 kB bundle is fine.
  build: { chunkSizeWarningLimit: 1024 },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', timeout: 900_000, proxyTimeout: 900_000 } },
  },
})
