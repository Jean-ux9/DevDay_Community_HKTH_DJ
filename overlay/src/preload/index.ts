import { contextBridge, ipcRenderer } from 'electron'
import type { PlatformBridge, CursorSample, HotkeyEvent, TransportEvent } from '../shared/app'
function listen<T>(channel: string, listener: (value: T) => void): () => void {
  const handler = (_event: unknown, value: T) => listener(value)
  ipcRenderer.on(channel, handler)
  return () => ipcRenderer.removeListener(channel, handler)
}
const bridge: PlatformBridge = {
  config: () => ipcRenderer.invoke('gaze:config'),
  onCursor: cb => listen<CursorSample>('gaze:cursor', cb),
  onHotkey: cb => listen<HotkeyEvent>('gaze:hotkey', cb),
  onVisibility: cb => listen<boolean>('gaze:visible', cb),
  cameraStatus: request => ipcRenderer.invoke('gaze:camera', request === true),
  windowPolicy: policy => ipcRenderer.send('gaze:policy', policy),
  connect: id => ipcRenderer.send('gaze:connect', id),
  send: (id, data) => ipcRenderer.send('gaze:send', id, data),
  close: id => ipcRenderer.send('gaze:close', id),
  onTransport: cb => listen<TransportEvent>('gaze:transport', cb)
}
contextBridge.exposeInMainWorld('gazePlatform', bridge)
