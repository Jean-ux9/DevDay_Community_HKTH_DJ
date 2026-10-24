import type { PlatformBridge } from '../../shared/app'
import type { GazeProvider, GazeSample } from './GazeProvider'
/** Reads cursor IPC, including over click-through windows. Never moves the cursor. */
export class MouseGazeProvider implements GazeProvider {
  private readonly listeners = new Set<(sample: GazeSample) => void>()
  private off: (() => void) | null = null
  constructor(private readonly bridge: Pick<PlatformBridge, 'onCursor'>) {}
  async start(): Promise<void> {
    if (this.off) return
    this.off = this.bridge.onCursor(sample => {
      for (const listener of this.listeners) listener({ ...sample, t: performance.now(), confidence: 1 })
    })
  }
  stop(): void { this.off?.(); this.off = null }
  onSample(callback: (sample: GazeSample) => void): () => void {
    this.listeners.add(callback)
    return () => { this.listeners.delete(callback) }
  }
}
