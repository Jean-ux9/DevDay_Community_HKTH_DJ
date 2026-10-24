import { BrowserWindow, app } from 'electron'
import { APP_NAME } from '../shared/app'
import { DEFAULT_PORT, buildLaunch } from './agent'

// Skeleton only: window flags, click-through, hotkeys and agent spawning come with the main-process step.
const launch = buildLaunch(process.env, DEFAULT_PORT)

app.whenReady().then(() => {
  const win = new BrowserWindow({ title: APP_NAME, width: 1280, height: 720 })
  if (process.env.ELECTRON_RENDERER_URL) void win.loadURL(process.env.ELECTRON_RENDERER_URL)
  console.log(`[main] agent command: ${launch.command}`)
})

app.on('window-all-closed', () => app.quit())
