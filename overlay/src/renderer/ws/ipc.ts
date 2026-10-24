import type { PlatformBridge } from '../../shared/app'
import type { SocketLike } from './client'
/** Socket adapter preserving the tested WS client while main retains panic access. */
export class IpcSocket implements SocketLike {
  onopen: SocketLike['onopen'] = null
  onmessage: SocketLike['onmessage'] = null
  onclose: SocketLike['onclose'] = null
  onerror: SocketLike['onerror'] = null
  private readonly id = crypto.randomUUID()
  private readonly unsubscribe: () => void
  constructor(private readonly bridge: PlatformBridge) {
    this.unsubscribe = bridge.onTransport(event => {
      if (event.id !== this.id) return
      if (event.type === 'open') this.onopen?.({})
      else if (event.type === 'message') this.onmessage?.({ data: event.data })
      else { this.unsubscribe(); this.onclose?.({ code: event.code, reason: event.reason }) }
    })
    bridge.connect(this.id)
  }
  send(data: string): void { this.bridge.send(this.id, data) }
  close(): void { this.unsubscribe(); this.bridge.close(this.id) }
}
