import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

// Django runs on 8000; Vite serves the app on 5050 because the EVE application's registered
// callback is http://localhost:5050/callback, so login round-trips through this server.
const backend = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000' // not localhost: Node may try ::1 first and stall

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    // Loopback only: not '::' or true, which would expose the dev server (with dev-login) on the LAN.
    host: '127.0.0.1',
    port: 5050,
    strictPort: true,
    proxy: {
      '/api': backend,
      '/auth': backend,
      '/callback': backend,
      '/admin': backend,
      '/static': backend,
    },
  },
  test: {
    environment: 'node',
    passWithNoTests: true,
  },
})
