import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
  build: {
    rollupOptions: {
      input: {
        landing: resolve(__dirname, 'index.html'),
        app: resolve(__dirname, 'app.html'),
        panelBid: resolve(__dirname, 'landing/panel-1-bid.html'),
        panelShadow: resolve(__dirname, 'landing/panel-2-shadow.html'),
        panelSettlement: resolve(__dirname, 'landing/panel-3-settlement.html'),
      },
    },
  },
})
