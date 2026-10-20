import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/repos': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/query': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/graph': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 4173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/repos': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/query': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/graph': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
});
