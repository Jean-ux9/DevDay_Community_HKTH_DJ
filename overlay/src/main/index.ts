import { BrowserWindow, app, globalShortcut, ipcMain, screen, session, shell, systemPreferences } from 'electron'
import { resolve } from 'node:path'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import type { ChildProcess } from 'node:child_process'
import { config as loadEnv } from 'dotenv'
import WebSocket from 'ws'
import { APP_NAME, type CameraStatus, type WindowPolicy } from '../shared/app'
import { buildLaunch, chooseAgent, describeExit, describeLaunch, freePort, killAgent, liveConfigProblems, running, spawnAgent, stopAgent } from './agent'
import { AgentTransport } from './transport'
import { CLICK_HOTKEY, HEAD_POINTER_HOTKEY, ignoreMouse, MOUSE_HOTKEY, QUIT_HOTKEY, STOP_HOTKEY } from './window'
const here = fileURLToPath(new URL('.', import.meta.url))
const repo = resolve(here, '../../..')
// Read before .env: only the launcher (scripts/start.sh, scripts/dev.sh) selects the agent.
const requestedMode = process.env.GAZE_AGENT_MODE
const shellNames = new Set(Object.keys(process.env))
const fileNames = Object.keys(loadEnv({ path: resolve(repo, '.env'), quiet: true }).parsed ?? {})
let agent: ChildProcess | null = null
let cleanup = async () => { if (agent) await stopAgent(agent) }
let quitting = false, cleaned = false
app.whenReady().then(async () => {
  const choice = chooseAgent(requestedMode, process.env)
  const problems = 'error' in choice ? [choice.error] : choice.mode === 'live' ? liveConfigProblems(process.env) : []
  if ('error' in choice || problems.length) {
    // A live setup error stays an error: no window, no agent, nothing that looks like it works.
    for (const problem of problems) console.error(`[agent] ${problem}`)
    if (!('error' in choice)) console.error('[agent] Live setup is incomplete: fix .env or the shell, then run scripts/start.sh live again.')
    app.exit(1)
    return
  }
  const requested = Number(process.env.GAZE_PORT || 0)
  const launch = buildLaunch(choice, await freePort(Number.isInteger(requested) && requested > 0 && requested < 65536 ? requested : 0))
  for (const line of describeLaunch(launch, process.env, new Set(fileNames.filter(name => shellNames.has(name))))) console.log(line)
  const child = agent = spawnAgent(launch, repo, process.env)
  // workArea, not bounds: macOS keeps windows off the menu bar, which pushed a full-height window
  // down and cut off its bottom edge.
  const win = new BrowserWindow({ title: APP_NAME, ...screen.getPrimaryDisplay().workArea,
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
  // An agent that is gone shows as an error in the overlay, not as "Reconnecting…" forever.
  child.on('error', error => {
    console.error('[agent] launch failed:', error.message)
    if (!quitting) transport.agentExited('The agent could not start')
  })
  child.on('exit', (code, signal) => {
    if (quitting) return
    console.error(`[agent] The agent ${describeExit(code, signal)}. Quit (⌃⌥⌘Q or Ctrl+C) and start again.`)
    transport.agentExited(`The agent ${describeExit(code, signal)}`)
  })
  const trusted = (event: { sender: unknown }) => event.sender === win.webContents
  const camera = (): CameraStatus => process.platform === 'darwin' ? systemPreferences.getMediaAccessStatus('camera') : 'unknown'
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
    callback(contents === win.webContents && permission === 'media' && 'mediaTypes' in details && (details.mediaTypes ?? []).every(type => type === 'video'))
  })
  ipcMain.handle('gaze:config', event => {
    if (!trusted(event)) throw new Error('Untrusted renderer')
    return { port: launch.port, token: launch.token, camera: camera(),
      gazeSource: process.env.GAZE_SOURCE === 'mouse' ? 'mouse' : 'webgazer', debug: process.env.DEBUG === '1' || process.env.GAZE_SOURCE === 'mouse',
      clickMode: process.env.GAZE_CLICK_MODE === '1', demoMode: process.env.GAZE_DEMO_UI === '1' }
  })
  ipcMain.handle('gaze:camera', async (event, request: boolean) => {
    if (!trusted(event)) throw new Error('Untrusted renderer')
    if (request && process.platform === 'darwin') {
      if (camera() === 'not-determined') {
        // The system prompt opens beneath this screen-saver-level window: step aside until answered.
        const shown = win.isVisible()
        if (shown) win.hide()
        try { await systemPreferences.askForMediaAccess('camera') } finally { if (shown && !win.isDestroyed()) win.showInactive() }
      }
      else if (camera() !== 'granted') await shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_Camera')
    }
    return camera()
  })
  ipcMain.on('gaze:policy', (event, policy: WindowPolicy) => {
    if (trusted(event) && policy && ['taskActive', 'confirming', 'caregiverHover'].every(key => typeof policy[key as keyof WindowPolicy] === 'boolean')) {
      win.setIgnoreMouseEvents(ignoreMouse(policy), { forward: true })
    }
  })
  ipcMain.on('gaze:quit', event => { if (trusted(event)) app.quit() })
  ipcMain.handle('gaze:debug-save', async (event, name: string, json: string) => {
    // Calibration logs for offline tuning: numbers only (no images), into a git-ignored folder.
    if (!trusted(event) || typeof name !== 'string' || !/^[a-z0-9-]{1,80}\.json$/.test(name) || typeof json !== 'string' || json.length > 20_000_000) return null
    const dir = resolve(repo, '.debug')
    await mkdir(dir, { recursive: true })
    const path = resolve(dir, name)
    await writeFile(path, json)
    console.log(`[debug] wrote ${path}`)
    return path
  })
  // Calibration samples (numbers only) in the app's data folder: survives restarts and port changes.
  const calibrationFile = (source: unknown) =>
    source === 'head' || source === 'webgazer' ? resolve(app.getPath('userData'), `calibration-${source}.json`) : null
  ipcMain.on('gaze:calibration-load', (event, source) => {
    const file = trusted(event) ? calibrationFile(source) : null
    try { event.returnValue = file && existsSync(file) ? readFileSync(file, 'utf8') : null } catch { event.returnValue = null }
  })
  ipcMain.on('gaze:calibration-save', (event, source, json: string) => {
    const file = trusted(event) ? calibrationFile(source) : null
    if (file && typeof json === 'string' && json.length <= 5_000_000) try { writeFileSync(file, json) } catch { /* this launch only */ }
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
  if (!globalShortcut.register(CLICK_HOTKEY, () => send('gaze:hotkey', 'toggle-click'))) console.error('[main] Click-mode shortcut unavailable')
  if (!globalShortcut.register(HEAD_POINTER_HOTKEY, () => send('gaze:hotkey', 'toggle-head-pointer'))) console.error('[main] Head pointer shortcut unavailable')
  if (!globalShortcut.register(QUIT_HOTKEY, () => app.quit())) console.error('[main] Quit shortcut unavailable')
  win.on('hide', () => send('gaze:visible', false))
  win.on('show', () => send('gaze:visible', true))
  const resize = () => win.setBounds(screen.getPrimaryDisplay().workArea)
  screen.on('display-metrics-changed', resize)
  const resetRenderer = () => { transport.close(); win.setIgnoreMouseEvents(true, { forward: true }) }
  win.webContents.on('render-process-gone', resetRenderer)
  win.webContents.on('did-start-loading', resetRenderer)
  win.once('ready-to-show', () => win.showInactive())
  cleanup = async () => {
    clearInterval(timer); globalShortcut.unregisterAll(); screen.removeListener('display-metrics-changed', resize)
    if (!win.isDestroyed()) win.hide() // gone at once, while the agent takes up to a few seconds to stop
    transport.close()
    await stopAgent(child)
  }
  if (process.env.ELECTRON_RENDERER_URL) await win.loadURL(process.env.ELECTRON_RENDERER_URL)
  else if (existsSync(resolve(here, '../renderer/index.html'))) await win.loadFile(resolve(here, '../renderer/index.html'))
}).catch(error => { console.error(error); app.quit() })
// Quit waits (bounded) for the agent to stop its task and exit, so a live agent never outlives the overlay.
app.on('before-quit', event => {
  if (cleaned) return
  event.preventDefault()
  if (quitting) return
  quitting = true
  setTimeout(() => app.exit(0), 5000)
  void cleanup().catch(error => console.error(error)).finally(() => { cleaned = true; app.quit() })
})
process.on('exit', () => { if (agent && running(agent)) killAgent(agent, 'SIGKILL') })
app.on('window-all-closed', () => app.quit())
