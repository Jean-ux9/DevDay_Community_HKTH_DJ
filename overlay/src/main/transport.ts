import { randomUUID } from 'node:crypto'
import type { TransportEvent } from '../shared/app'
export interface MainSocket {
  readyState: number
  send(data: string): void
  close(): void
  on(event: 'open', cb: () => void): unknown
  on(event: 'message', cb: (data: { toString(): string }) => void): unknown
  on(event: 'close', cb: (code: number, reason: { toString(): string }) => void): unknown
  on(event: 'error', cb: () => void): unknown
}
/** Main owns the same socket used by the renderer, so panic works even if React stalls. */
export class AgentTransport {
  private current: { id: string; socket: MainSocket; helloSent: boolean } | null = null
  constructor(private readonly create: () => MainSocket, private readonly emit: (event: TransportEvent) => void) {}
  connect(id: string): void {
    this.close()
    const socket = this.create()
    this.current = { id, socket, helloSent: false }
    const live = () => this.current?.socket === socket
    socket.on('open', () => { if (live()) this.emit({ id, type: 'open' }) })
    socket.on('message', data => { if (live()) this.emit({ id, type: 'message', data: data.toString() }) })
    socket.on('close', (code, reason) => { if (live()) { this.current = null; this.emit({ id, type: 'close', code, reason: reason.toString() }) } })
    socket.on('error', () => { /* close drives reconnect */ })
  }
  send(id: string, data: string): boolean {
    if (this.current?.id !== id || this.current.socket.readyState !== 1) return false
    this.current.socket.send(data)
    if (!this.current.helloSent) {
      try { this.current.helloSent = JSON.parse(data).type === 'hello' } catch { /* renderer validates frames */ }
    }
    return true
  }
  panic(): boolean {
    if (!this.current?.helloSent) return false
    return this.send(this.current.id, JSON.stringify({ v: 1, type: 'stop', id: randomUUID(), re: null,
      ts: Date.now(), payload: { reason: 'hotkey' } }))
  }
  close(id?: string): void {
    if (!this.current || (id && this.current.id !== id)) return
    const socket = this.current.socket
    this.current = null
    socket.close()
  }
}
