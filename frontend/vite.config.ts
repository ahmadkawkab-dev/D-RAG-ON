import fs from 'node:fs'
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react(), tailwindcss()],

  server: {
    host: 'localhost',
    port: 5173,
    strictPort: true,
    https: {
      key: fs.readFileSync('/mnt/c/dev-certs/localhost-key.pem'),
      cert: fs.readFileSync('/mnt/c/dev-certs/localhost.pem'),
    },
  },

  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
})