import { BrowserWindow, app, globalShortcut, ipcMain, screen, session, shell, systemPreferences } from 'electron'
import { resolve } from 'node:path'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { config as loadEnv } from 'dotenv'
import WebSocket from 'ws'
import { APP_NAME, type CameraStatus, type WindowPolicy } from '../shared/app'
import { buildLaunch, freePort, spawnAgent, killAgent } from './agent'
import { AgentTransport } from './transport'
import { ignoreMouse, MOUSE_HOTKEY, STOP_HOTKEY } from './window'
const here = fileURLToPath(new URL('.', import.meta.url))
const repo = resolve(here, '../../..')
loadEnv({ path: resolve(repo, '.env'), quiet: true })
let cleanup = () => {}
app.whenReady().then(async () => {
  const requested = Number(process.env.GAZE_PORT || 0)
  const launch = buildLaunch(process.env, await freePort(Number.isInteger(requested) && requested > 0 && requested < 65536 ? requested : 0))
  const child = spawnAgent(launch, repo, process.env)
  child.on('error', error => console.error('[agent] launch failed:', error.message))
  const win = new BrowserWindow({ title: APP_NAME, ...screen.getPrimaryDisplay().bounds,
    transparent: true, backgroundColor: '#00000000', frame: false, alwaysOnTop: true,
    focusable: false, type: 'panel', skipTaskbar: true, show: false, resizable: false,
    webPreferences: { preload: resolve(here, '../preload/index.js'), contextIsolation: true,
      nodeIntegration: false, sandbox: true, backgroundThrottling: false, focusOnNavigation: false } })
  win.setAlwaysOnTop(true, 'screen-saver')
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  win.setIgnoreMouseEvents(true, { forward: true })
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  win.webContents.on('will-navigate', event => event.preventDefault())
  const send = (channel: string, data: unknown) => { if (!win.isDestroyed()) win.webContents.send(channel, data) }
  const transport = new AgentTransport(() => new WebSocket(`ws://127.0.0.1:${launch.port}/?token=${launch.token}`), event => send('gaze:transport', event))
  const trusted = (event: { sender: unknown }) => event.sender === win.webContents
  const camera = (): CameraStatus => process.platform === 'darwin' ? systemPreferences.getMediaAccessStatus('camera') : 'unknown'
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
    callback(contents === win.webContents && permission === 'media' && 'mediaTypes' in details && (details.mediaTypes ?? []).every(type => type === 'video'))
  })
  ipcMain.handle('gaze:config', event => {
    if (!trusted(event)) throw new Error('Untrusted renderer')
    return { port: launch.port, token: launch.token, camera: camera(),
      gazeSource: process.env.GAZE_SOURCE === 'mouse' ? 'mouse' : 'webgazer', debug: process.env.DEBUG === '1' || process.env.GAZE_SOURCE === 'mouse' }
  })
  ipcMain.handle('gaze:camera', async (event, request: boolean) => {
    if (!trusted(event)) throw new Error('Untrusted renderer')
    if (request && process.platform === 'darwin') {
      if (camera() === 'not-determined') await systemPreferences.askForMediaAccess('camera')
      else if (camera() !== 'granted') await shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_Camera')
    }
    return camera()
  })
  ipcMain.on('gaze:policy', (event, policy: WindowPolicy) => {
    if (trusted(event) && policy && ['taskActive', 'confirming', 'caregiverHover'].every(key => typeof policy[key as keyof WindowPolicy] === 'boolean')) {
      win.setIgnoreMouseEvents(ignoreMouse(policy), { forward: true })
    }
  })
  ipcMain.on('gaze:connect', (event, id: string) => { if (trusted(event) && typeof id === 'string') transport.connect(id) })
  ipcMain.on('gaze:send', (event, id: string, data: string) => { if (trusted(event) && typeof data === 'string' && data.length <= 1_000_000) transport.send(id, data) })
  ipcMain.on('gaze:close', (event, id: string) => { if (trusted(event)) transport.close(id) })
  const timer = setInterval(() => {
    const point = screen.getCursorScreenPoint(), bounds = win.getBounds()
    send('gaze:cursor', { x: point.x - bounds.x, y: point.y - bounds.y, t: performance.now() })
  }, 1000 / 60)
  if (!globalShortcut.register(STOP_HOTKEY, () => {
    transport.panic()
    send('gaze:hotkey', 'stop')
    if (win.isVisible()) win.hide(); else win.showInactive()
  })) console.error('[main] STOP shortcut unavailable')
  if (!globalShortcut.register(MOUSE_HOTKEY, () => send('gaze:hotkey', 'toggle-source'))) console.error('[main] Mouse shortcut unavailable')
  win.on('hide', () => send('gaze:visible', false))
  win.on('show', () => send('gaze:visible', true))
  const resize = () => win.setBounds(screen.getPrimaryDisplay().bounds)
  screen.on('display-metrics-changed', resize)
  const resetRenderer = () => { transport.close(); win.setIgnoreMouseEvents(true, { forward: true }) }
  win.webContents.on('render-process-gone', resetRenderer)
  win.webContents.on('did-start-loading', resetRenderer)
  win.once('ready-to-show', () => win.showInactive())
  cleanup = () => { clearInterval(timer); transport.close(); killAgent(child); globalShortcut.unregisterAll(); screen.removeListener('display-metrics-changed', resize) }
  if (process.env.ELECTRON_RENDERER_URL) await win.loadURL(process.env.ELECTRON_RENDERER_URL)
  else if (existsSync(resolve(here, '../renderer/index.html'))) await win.loadFile(resolve(here, '../renderer/index.html'))
}).catch(error => { console.error(error); cleanup(); app.quit() })
app.on('before-quit', () => cleanup())
app.on('window-all-closed', () => app.quit())
