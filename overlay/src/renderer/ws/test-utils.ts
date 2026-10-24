// Test helpers: a scripted socket and a replayer for frames recorded from scripts/fake_agent.py
// (see overlay/scripts/record_frames.py). Only tests import this file.
import type { SocketLike } from './client'
import { GazeWsClient } from './client'
import type { AgentToOverlay, OverlayToAgent } from './protocol.gen'

export class FakeSocket implements SocketLike {
  onopen: SocketLike['onopen'] = null
  onmessage: SocketLike['onmessage'] = null
  onclose: SocketLike['onclose'] = null
  onerror: SocketLike['onerror'] = null
  sent: OverlayToAgent[] = []
  closed = false

  send(data: string): void {
    this.sent.push(JSON.parse(data) as OverlayToAgent)
  }

  close(): void {
    this.closed = true
  }

  open(): void {
    this.onopen?.({})
  }

  /** Delivers a frame (object → JSON, string as-is). */
  deliver(frame: unknown): void {
    this.onmessage?.({ data: typeof frame === 'string' ? frame : JSON.stringify(frame) })
  }

  drop(code = 1006): void {
    this.onclose?.({ code })
  }
}

export interface Rig {
  client: GazeWsClient
  sockets: FakeSocket[]
  diagnostics: { kind: string; detail: string }[]
  socket: () => FakeSocket
}

export function makeRig(initialMode?: 'auto' | 'type'): Rig {
  const sockets: FakeSocket[] = []
  const diagnostics: { kind: string; detail: string }[] = []
  const client = new GazeWsClient({
    url: 'ws://127.0.0.1:0/?token=test',
    initialMode,
    createSocket: () => {
      const s = new FakeSocket()
      sockets.push(s)
      return s
    },
    onDiagnostic: (kind, detail) => diagnostics.push({ kind, detail })
  })
  return { client, sockets, diagnostics, socket: () => sockets[sockets.length - 1]! }
}

export interface RecordedFrame {
  dir: 'in' | 'out'
  msg: Record<string, unknown> & { id: string; re: string | null; type: string; payload: Record<string, unknown> }
  /** For `in` frames: index (in the flow) of the `out` frame this one answers. */
  re_out?: number | null
}

export interface RecordedFlow {
  flow: string
  frames: RecordedFrame[]
}

/**
 * Replays a recorded flow against an opened client (see `open`): `out` frames are sent through the
 * client (so its bookkeeping sees them), `in` frames are delivered from the agent with `re` pointing
 * at the id the client really used. Stops after the first frame `until` accepts, and returns where to
 * `resume` from.
 */
export interface ReplayCursor {
  from: number
  sentIds: string[]
}

export function replay(
  rig: Rig,
  flow: RecordedFlow,
  until?: (frame: RecordedFrame, index: number) => boolean,
  resume: ReplayCursor = { from: 0, sentIds: [] }
): ReplayCursor {
  const sentIds = resume.sentIds
  const socket = rig.socket()
  let next = flow.frames.length
  for (const [i, frame] of flow.frames.entries()) {
    if (i < resume.from) continue
    if (frame.dir === 'out') {
      if (i === 0 && frame.msg.type === 'hello') {
        sentIds[i] = socket.sent[0]!.id // the client sent its own hello when the socket opened
      } else {
        const sent = rig.client.send(frame.msg.type as OverlayToAgent['type'], frame.msg.payload as never, frame.msg.re)
        if (!sent) throw new Error(`client refused to send ${frame.msg.type}`)
        sentIds[i] = sent.id
      }
    } else {
      const re = frame.re_out != null ? (sentIds[frame.re_out] ?? null) : frame.msg.re
      socket.deliver({ ...frame.msg, re } as unknown as AgentToOverlay)
    }
    if (until?.(frame, i)) {
      next = i + 1
      break
    }
  }
  return { from: next, sentIds }
}

/** Starts the client and opens its socket (it sends hello); the caller delivers hello_ack. */
export function open(rig: Rig): void {
  rig.client.start()
  rig.socket().open()
}

/** Opens the connection and completes the handshake with a minimal valid hello_ack. */
export function connect(rig: Rig, ack?: unknown): void {
  open(rig)
  const socket = rig.socket()
  socket.deliver(ack ?? helloAck(socket.sent[0]!.id))
}

export const helloAck = (re: string, id = '00000000-0000-4000-8000-000000000001') => ({
  v: 1,
  type: 'hello_ack',
  id,
  re,
  ts: 1,
  payload: {
    version: '0.1.0',
    demo_mode: true,
    profile: {
      name: 'Alex',
      favorites: { artist: 'Taylor Swift', playlist: 'Deep Focus', sites: ['ticketmaster.com'] },
      contacts: { Mom: ['+15550100'] },
      style: { tone: 'casual', signature: '', phrases: ['on my way'] },
      address: { full_name: 'Alex', city: 'Austin', email: 'alex@example.com' }
    },
    settings: { dwellMs: 800, blinkSelect: false, density: 'large', gazeSource: 'webgazer', calibrationMode: 'gaze' },
    permissions: { accessibility: true, screen_recording: true, camera: 'unknown' }
  }
})
