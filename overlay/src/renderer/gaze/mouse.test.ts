import { describe, expect, it, vi } from 'vitest'
import { MouseGazeProvider } from './mouse'
import type { CursorSample } from '../../shared/app'
describe('MouseGazeProvider', () => {
  it('converts cursor IPC to confidence-1 gaze without DOM mouse events and cleans up', async () => {
    let emit: (sample: CursorSample) => void = () => {}
    const off = vi.fn()
    const onCursor = vi.fn(cb => { emit = cb; return off })
    const provider = new MouseGazeProvider({ onCursor })
    const heard = vi.fn(), unsubscribe = provider.onSample(heard)
    await provider.start(); await provider.start()
    emit({ x: 400, y: 300, t: 5 })
    expect(heard).toHaveBeenCalledWith({ x: 400, y: 300, t: expect.any(Number), confidence: 1 })
    expect(onCursor).toHaveBeenCalledTimes(1)
    unsubscribe(); emit({ x: 0, y: 0, t: 6 })
    expect(heard).toHaveBeenCalledTimes(1)
    provider.stop(); expect(off).toHaveBeenCalledTimes(1)
  })
})
