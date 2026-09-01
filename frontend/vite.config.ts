import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // Listen on all IP addresses (for Docker)
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://backend:8000', // Docker compose service name
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
