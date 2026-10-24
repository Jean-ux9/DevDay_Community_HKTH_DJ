/// <reference types="vite/client" />
import { StrictMode, type JSX } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './styles/base.css'
import './styles/overlay.css'
import './styles/dwell.css'
import './styles/dev.css'

type TransportListener = Parameters<NonNullable<Window['gazePlatform']>['onTransport']>[0]
type HotkeyListener = Parameters<NonNullable<Window['gazePlatform']>['onHotkey']>[0]
// No ⌃⌥⌘. here: in Electron, main itself sends that stop to the agent; use the STOP target instead.
const HOTKEYS: Record<string, Parameters<HotkeyListener>[0]> = { KeyM: 'toggle-source', KeyD: 'toggle-click' }

/**
 * Dev only, plain browser (no Electron preload): stand in for the preload bridge so the real
 * platform runs against the fake agent. The cursor is the gaze (hover, no clicks), re-sent at
 * 60 Hz like Electron main does, and the WebSocket goes straight to the agent.
 * Open http://localhost:5173/?port=<GAZE_PORT>&token=<GAZE_TOKEN>[&bg=busy|light|dark|none]
 * [&gaze=webgazer&camera=denied|not-determined|granted] to preview the permissions checklist
 * [&click=1] to start in click mode. Hotkeys as in Electron: ⌃⌥⌘M gaze source, ⌃⌥⌘D click mode.
 */
function installBrowserBridge(): void {
  const params = new URLSearchParams(location.search)
  const port = Number(params.get('port') ?? 0)
  const token = params.get('token') ?? 'dev-token'
  const gazeSource = params.get('gaze') === 'webgazer' ? 'webgazer' : 'mouse'
  const cameras = ['not-determined', 'granted', 'denied', 'restricted', 'unknown'] as const
  const camera = cameras.find(c => c === params.get('camera')) ?? 'unknown'
  let cursor: { x: number; y: number } | null = null
  addEventListener('mousemove', e => { cursor = { x: e.clientX, y: e.clientY } })
  document.documentElement.addEventListener('mouseleave', () => { cursor = null })
  const sockets = new Map<string, WebSocket>()
  const transport = new Set<TransportListener>()
  const emit: TransportListener = event => { for (const listener of transport) listener(event) }
  window.gazePlatform = {
    config: async () => ({ port, token, gazeSource, debug: true, camera, clickMode: params.get('click') === '1' }),
    onCursor: listener => {
      const timer = setInterval(() => { if (cursor) listener({ ...cursor, t: performance.now() }) }, 16)
      return () => clearInterval(timer)
    },
    onHotkey: listener => {
      const onKey = (e: KeyboardEvent) => {
        const event = e.ctrlKey && e.altKey && e.metaKey ? HOTKEYS[e.code] : undefined
        if (event) { e.preventDefault(); listener(event) }
      }
      addEventListener('keydown', onKey)
      return () => removeEventListener('keydown', onKey)
    },
    onVisibility: () => () => {},
    cameraStatus: async () => camera,
    windowPolicy: () => {},
    connect: id => {
      const ws = new WebSocket(`ws://127.0.0.1:${port}/?token=${encodeURIComponent(token)}`)
      sockets.set(id, ws)
      ws.onopen = () => emit({ id, type: 'open' })
      ws.onmessage = e => emit({ id, type: 'message', data: String(e.data) })
      ws.onclose = e => { sockets.delete(id); emit({ id, type: 'close', code: e.code, reason: e.reason }) }
    },
    send: (id, data) => sockets.get(id)?.send(data),
    close: id => sockets.get(id)?.close(),
    onTransport: listener => { transport.add(listener); return () => { transport.delete(listener) } }
  }
}

/** A stand-in "desktop" behind the overlay, to judge legibility over busy content in a browser. */
function DevBackdrop({ kind }: { kind: string }): JSX.Element | null {
  if (kind === 'none') return null
  const lines = Array.from({ length: 40 }, (_, i) =>
    `Inbox · Lunch Friday? · Re: quarterly numbers ${i} · Your order has shipped · Meeting moved to 3pm`)
  return (
    <div className={`dev-backdrop dev-${kind}`} aria-hidden="true">
      <div className="dev-window">
        <div className="dev-titlebar">Mail — Inbox (3)</div>
        {lines.map((line, i) => <p key={i}>{line}</p>)}
      </div>
      <div className="dev-blob dev-blob-a" /><div className="dev-blob dev-blob-b" />
    </div>
  )
}

const browser = import.meta.env.DEV && !window.gazePlatform
if (browser) installBrowserBridge()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {browser && <DevBackdrop kind={new URLSearchParams(location.search).get('bg') ?? 'busy'} />}
    <App />
  </StrictMode>
)
