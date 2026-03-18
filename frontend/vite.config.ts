import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  },
  define: {
    // Expose env variable to the app bundle
    __API_BASE_URL__: JSON.stringify(process.env.VITE_API_BASE_URL ?? ''),
  }
})
