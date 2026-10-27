import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

const apiTarget = process.env.VITE_API_PROXY ?? 'http://localhost:8015'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    // Never allow a second copy of React (the cause of "Invalid hook call").
    dedupe: ['react', 'react-dom'],
  },
  // Pre-bundle every runtime dependency up front. If Vite discovers one mid-session it re-optimizes and can
  // serve react and react-dom from different bundle versions, which breaks hooks until the cache is cleared.
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-dom/client',
      'react/jsx-runtime',
      'react/jsx-dev-runtime',
      'react-router-dom',
      '@tanstack/react-query',
      'zustand',
      'lucide-react',
      'clsx',
    ],
  },
  server: {
    proxy: { '/api': { target: apiTarget, changeOrigin: false } },
    // Public hostnames (e.g. the Cloudflare Tunnel domain) that may reach the dev server.
    allowedHosts: process.env.VITE_ALLOWED_HOSTS?.split(',').filter(Boolean),
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
