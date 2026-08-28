import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend upstream: local dev hits localhost; docker compose sets API_UPSTREAM
const upstream = process.env.API_UPSTREAM || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true, // dev server behind a preview proxy; compose serves build via nginx in prod notes
    proxy: {
      '/api': { target: upstream, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') },
    },
  },
})
