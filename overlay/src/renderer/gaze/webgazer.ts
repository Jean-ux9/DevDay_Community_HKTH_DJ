import type { GazeProvider, GazeSample } from './GazeProvider'
export interface WebGazerApi {
  params: { faceMeshSolutionPath: string }
  setGazeListener(callback: (point: { x: number; y: number } | null) => void): WebGazerApi
  applyKalmanFilter(value: boolean): WebGazerApi
  showVideoPreview(value: boolean): WebGazerApi
  showPredictionPoints(value: boolean): WebGazerApi
  saveDataAcrossSessions(value: boolean): WebGazerApi
  removeMouseEventListeners(): WebGazerApi
  recordScreenPosition(x: number, y: number, type: 'click'): WebGazerApi
  begin(): Promise<WebGazerApi>
  pause(): WebGazerApi
  resume(): Promise<WebGazerApi>
  end(): WebGazerApi
  stopVideo(): WebGazerApi
}
let loading: Promise<WebGazerApi> | null = null
/** Use the vendor's browser bundle: its MediaPipe dependency is a classic script, not ESM. */
export const loadWebGazer = (): Promise<WebGazerApi> => {
  const host = window as Window & { webgazer?: WebGazerApi }
  if (host.webgazer) return Promise.resolve(host.webgazer)
  if (!loading) loading = new Promise<WebGazerApi>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = new URL('./gaze-assets/webgazer.js', location.href).href
    script.onload = () => host.webgazer ? resolve(host.webgazer) : reject(new Error('WebGazer bundle did not initialize'))
    script.onerror = () => reject(new Error('Could not load local WebGazer bundle'))
    document.head.append(script)
  }).catch(error => { loading = null; throw error })
  return loading
}
export class WebGazerProvider implements GazeProvider {
  private api: WebGazerApi | null = null
  private active = false
  private initialized = false
  private readonly listeners = new Set<(sample: GazeSample) => void>()
  constructor(private readonly load = loadWebGazer) {}
  async start(): Promise<void> {
    if (this.active) return
    this.active = true
    try {
      const api = this.api ?? await this.load()
      this.api = api
      if (!this.active) return
      api.params.faceMeshSolutionPath = new URL('./gaze-assets/face_mesh/', location.href).href
      api.applyKalmanFilter(true).showPredictionPoints(false).saveDataAcrossSessions(false)
      api.setGazeListener(point => {
        if (!this.active) return
        // Missing eyes must invalidate the last point rather than keep dwelling it.
        for (const listener of this.listeners) listener({ x: point?.x ?? 0, y: point?.y ?? 0,
          t: performance.now(), confidence: point ? 1 : 0 })
      })
      if (!this.initialized) { await api.begin(); this.initialized = true }
      else await api.resume()
      api.removeMouseEventListeners().showVideoPreview(false)
      if (!this.active) this.release()
    } catch (error) { this.active = false; this.release(); throw error }
  }
  stop(): void { this.active = false; this.release() }
  private release(): void {
    if (this.api) {
      this.initialized = false
      this.api.pause()
      // WebGazer can fail halfway through begin(); partial DOM/camera cleanup must still run.
      try { this.api.stopVideo() } catch { /* no video stream was created */ }
      try { this.api.end() } catch { /* initialization did not create the DOM yet */ }
    }
  }
  train(x: number, y: number): void { if (this.initialized) this.api?.recordScreenPosition(x, y, 'click') }
  onSample(callback: (sample: GazeSample) => void): () => void {
    this.listeners.add(callback)
    return () => { this.listeners.delete(callback) }
  }
}
