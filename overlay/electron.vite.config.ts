import { resolve } from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'electron-vite'
export default defineConfig({
  main: {},
  preload: { build: { rollupOptions: { output: { format: 'cjs', entryFileNames: 'index.js' } } } },
  renderer: {
    base: './',
    publicDir: resolve(__dirname, 'node_modules/.gaze-assets'),
    plugins: [react()],
    // Bundle-check the A1 contract even before A1's entrypoint imports it.
    build: { rollupOptions: { input: {
      index: resolve(__dirname, 'src/renderer/index.html'),
      platform: resolve(__dirname, 'src/renderer/platform/index.ts')
    }, preserveEntrySignatures: 'exports-only' } },
    server: { fs: { allow: [resolve(__dirname, '..')] } }
  }
})
