import path from "path"
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  define: {
    // Baked in at build time (Dockerfile ARG GIT_SHA); "dev" for local runs.
    __APP_COMMIT__: JSON.stringify((process.env.GIT_SHA ?? 'dev').slice(0, 8)),
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: 'jsdom',
    server: { deps: { inline: [/@mskcc/] } },
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
  server: {
    port: 5173,
    allowedHosts: ['host.docker.internal'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
