// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { WebGazerProvider, type WebGazerApi } from './webgazer'
const fakeApi = () => {
  let emit: (p: { x: number; y: number } | null) => void = () => {}
  const api = { params: { faceMeshSolutionPath: '' },
    setGazeListener: vi.fn((cb: (p: { x: number; y: number } | null) => void): WebGazerApi => { emit = cb; return api }),
    applyKalmanFilter: vi.fn((): WebGazerApi => api), showVideoPreview: vi.fn((): WebGazerApi => api), showPredictionPoints: vi.fn((): WebGazerApi => api),
    saveDataAcrossSessions: vi.fn((): WebGazerApi => api), removeMouseEventListeners: vi.fn((): WebGazerApi => api),
    recordScreenPosition: vi.fn((): WebGazerApi => api), begin: vi.fn(async (): Promise<WebGazerApi> => api), pause: vi.fn((): WebGazerApi => api),
    resume: vi.fn(async (): Promise<WebGazerApi> => api), end: vi.fn((): WebGazerApi => api), stopVideo: vi.fn((): WebGazerApi => api)
  } satisfies WebGazerApi
  return { api, emit: (p: { x: number; y: number } | null) => emit(p) }
}
describe('WebGazer adapter with a fake camera API', () => {
  it('enables Kalman, hides preview, disables mouse training, and invalidates lost eyes', async () => {
    const { api, emit } = fakeApi(), provider = new WebGazerProvider(async () => api), heard = vi.fn()
    provider.onSample(heard)
    await provider.start()
    expect(api.applyKalmanFilter).toHaveBeenCalledWith(true)
    expect(api.removeMouseEventListeners).toHaveBeenCalled()
    expect(api.showVideoPreview).toHaveBeenCalledWith(false)
    expect(api.saveDataAcrossSessions).toHaveBeenCalledWith(false)
    emit({ x: 100, y: 200 }); emit(null)
    expect(heard.mock.calls[0]![0]).toMatchObject({ x: 100, y: 200, confidence: 1 })
    expect(heard.mock.calls[1]![0].confidence).toBe(0)
    provider.train(400, 500)
    expect(api.recordScreenPosition).toHaveBeenCalledWith(400, 500, 'click')
    provider.stop()
    expect(api.stopVideo).toHaveBeenCalledTimes(1)
    expect(api.end).toHaveBeenCalledTimes(1)
  })
  it('releases the camera if stopped while initialization is in flight', async () => {
    const { api } = fakeApi()
    let finish: (api: WebGazerApi) => void = () => {}
    api.begin.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const provider = new WebGazerProvider(async () => api)
    const ready = provider.start()
    await Promise.resolve()
    provider.stop()
    api.stopVideo.mockClear()
    finish(api); await ready
    // Initialization finishing after stop must release the stream again.
    expect(api.stopVideo).toHaveBeenCalledTimes(1)
  })
})
