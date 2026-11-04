import { defineConfig } from 'vite';
import { resolve } from 'node:path';

export default defineConfig({
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8002', changeOrigin: true } } },
  build: {
    rollupOptions: {
      input: {
        main: resolve(import.meta.dirname, 'index.html'),
        auth: resolve(import.meta.dirname, 'auth/index.html'),
        app: resolve(import.meta.dirname, 'app/index.html'),
      },
    },
  },
});
