// Browser preview only (scripts/dev-browser.sh runs plain vite on this folder; Electron uses
// electron.vite.config.ts): serve the same local camera-model assets as Electron's renderer.
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
export default defineConfig({ publicDir: resolve(import.meta.dirname, '../../node_modules/.gaze-assets') })
