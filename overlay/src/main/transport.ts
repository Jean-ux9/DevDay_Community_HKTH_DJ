import { randomUUID } from 'node:crypto'
import type { TransportEvent } from '../shared/app'
/**
 * Close code main reports to the renderer once the agent process it spawned is gone: no agent will
 * ever listen on that port again, so reconnecting cannot help. Main and renderer only, never sent by an
 * agent (the renderer's copy is AGENT_EXITED_CLOSE in renderer/ws/client.ts).
 */
export const AGENT_EXITED_CLOSE = 4500
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
  private exited: string | null = null
  constructor(private readonly create: () => MainSocket, private readonly emit: (event: TransportEvent) => void) {}
  connect(id: string): void {
    this.close()
    if (this.exited !== null) { this.emit({ id, type: 'close', code: AGENT_EXITED_CLOSE, reason: this.exited }); return }
    const socket = this.create()
    this.current = { id, socket, helloSent: false }
    const live = () => this.current?.socket === socket
    socket.on('open', () => { if (live()) this.emit({ id, type: 'open' }) })
    socket.on('message', data => { if (live()) this.emit({ id, type: 'message', data: data.toString() }) })
    socket.on('close', (code, reason) => { if (live()) { this.current = null; this.emit({ id, type: 'close', code, reason: reason.toString() }) } })
    socket.on('error', () => { /* close drives reconnect */ })
  }
  /** The agent process is gone: end the current connection and refuse new ones with AGENT_EXITED_CLOSE. */
  agentExited(reason: string): void {
    this.exited ??= reason
    const current = this.current
    if (!current) return
    this.current = null
    current.socket.close()
    this.emit({ id: current.id, type: 'close', code: AGENT_EXITED_CLOSE, reason: this.exited })
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
