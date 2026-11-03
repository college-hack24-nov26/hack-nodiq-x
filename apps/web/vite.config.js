import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
//
// changeOrigin: false is load-bearing for login. The string shorthand
// ('/api': 'http://…') makes Vite set changeOrigin: true, which rewrites the
// proxied Host header to 127.0.0.1:8001. The Flask CSRF/origin check trusts
// the CORS allow-list (ports 5173/4173 only) plus the request's own host —
// with Host rewritten, the own-host fallback can never match, so any dev
// server that lands on another port (Vite auto-increments to 5174 when 5173
// is taken) gets 403 "request rejected: untrusted origin" on login/signup.
// Preserving the original Host keeps the browser's origin verifiable, so any
// dev port works without widening the allow-list.
const proxy = {
  target: 'http://127.0.0.1:8001',
  changeOrigin: false,
}

export default defineConfig({
  envDir: '../../',
  plugins: [react()],
  server: {
    allowedHosts :['host.docker.internal'],
    proxy: {
      '/api': proxy,
      '/dataset': proxy,
    },
  },
})
