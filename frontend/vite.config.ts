import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  // Relative asset paths (./assets/...) keep the UI working when server mode is
  // published under a reverse-proxy sub-path.
  base: './',
  plugins: [react()],
  build: {
    // Never inline fonts as data: URLs: the CSP (index.html) allows fonts from 'self'
    // only, so an inlined font subset is silently blocked. Other small assets inline
    // as usual (undefined keeps Vite's default limit).
    assetsInlineLimit: (file: string) =>
      /\.(woff2?|ttf|otf|eot)$/i.test(file) ? false : undefined,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // E2E points this at its own backend; dev uses the backend on :8000.
        target: process.env.API_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
