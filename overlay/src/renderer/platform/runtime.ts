import type { CameraStatus, PlatformBridge, PlatformConfig, WindowPolicy } from '../../shared/app'
import { playSelectTick } from './sound'
import { dwellStore } from '../dwell/context'
import { PointFilter, STEADY_ONE_EURO } from '../gaze/filter'
import { MouseGazeProvider } from '../gaze/mouse'
import { MediaPipeGazeProvider } from '../gaze/mediapipe'
import { HeadPoseProvider } from '../gaze/headpose'
import { CalibrationController } from '../gaze/calibration'
import type { GazeProvider, GazeSample } from '../gaze/GazeProvider'
import { GazeWsClient } from '../ws/client'
import { IpcSocket } from '../ws/ipc'
import { initialSession, type SessionState as AgentSession } from '../ws/session'
export interface GazeState {
  /** webgazer = camera eye tracking (name kept for the settings schema); head = MediaPipe head pose. */
  source: 'webgazer' | 'mouse' | 'head'
  /** Overlay viewport coordinates in CSS px (matching DwellTarget DOM bounds). */
  point: { x: number; y: number } | null
  confidence: number
  debug: boolean
  error?: string | null
  /** Click mode: targets select on a real click; only STOP still selects by dwell. */
  clickMode: boolean
  /** Head pointer mode (e.g. macOS Head Pointer as the mouse): steadier smoothing; the UI keeps targets off the edges. */
  headPointer: boolean
  /** Demo mode: presenter pointer, select sound, fewer corners and no shortcut hints. A developer flag
   *  (GAZE_DEMO_UI=1, or ?demo=1 in the browser preview), not a user setting. */
  demoMode: boolean
}
export interface SessionState extends AgentSession {
  cameraStatus: CameraStatus
  permissions: { accessibility: boolean; screen_recording: boolean; camera: CameraStatus } | null
}
/** Magnetic targets in head pointer mode: px from a target's edge that still selects it. */
export const MAGNET_PX = 90
/** Drift correction: each on-target selection moves the offset this fraction toward the target centre. */
export const DRIFT_GAIN = 0.3
/** The offset never exceeds this (px per axis): a bad streak can't run the pointer away. */
export const MAX_OFFSET_PX = 300
/** Readable text for any thrown value: a failed script or asset load throws a bare DOM Event. */
const describeError = (error: unknown): string => error instanceof Error ? error.message
  : typeof Event !== 'undefined' && error instanceof Event ? 'The camera model could not load' : String(error)
/** Head pointer mode is overlay-local (the agent's settings schema is frozen): kept in localStorage. */
export const HEAD_POINTER_KEY = 'gaze.headPointer'
/** A camera source's calibration samples, so it calibrates once, not every launch. */
/** The custom-calibration pointer is head pose; the frozen settings' 'webgazer' value means "camera pointer". */
const fromSetting = (source: 'webgazer' | 'mouse'): GazeState['source'] => source === 'mouse' ? 'mouse' : 'head'
export const calibrationKey = (source: 'webgazer' | 'head'): string => `gaze.calibration.${source}`
interface CalibrationLog {
  target: string
  startedAt: string
  trains: { t: number; x: number; y: number }[]
  checkDots: { t: number; index: number; x: number; y: number }[]
}
export class PlatformRuntime {
  private readonly listeners = new Set<() => void>()
  private readonly gazeListeners = new Set<() => void>()
  private bridge: PlatformBridge | undefined
  private client: GazeWsClient | null = null
  private startup: Promise<void> | null = null
  private windowPolicy: WindowPolicy | null = null
  private disposed = false
  private visible = true
  private cameraReady = false
  private camera: CameraStatus = 'unknown'
  private settings: AgentSession['settings'] = null
  private lastSession = initialSession()
  private session: SessionState = { ...this.lastSession, cameraStatus: 'unknown', permissions: null }
  private gaze: GazeState = { source: 'mouse', point: null, confidence: 0, debug: true, error: null, clickMode: false, headPointer: false, demoMode: false }
  private latest: GazeSample | null = null
  private cursor: { x: number; y: number } | null = null
  private filter = new PointFilter()
  private provider: GazeProvider | null = null
  /** One tracker per camera source, kept across switches so its calibration isn't lost. */
  private readonly cameraProviders = new Map<'webgazer' | 'head', MediaPipeGazeProvider>()
  private providerOff: (() => void) | null = null
  private providerJob: Promise<void> = Promise.resolve()
  private readonly cleanups: (() => void)[] = []
  private frame = 0
  readonly validation = new CalibrationController()
  /** Debug: what happened during the current calibration, exported with exportCalibration(). */
  private calibrationLog: CalibrationLog | null = null
  /** The calibrated source to return to when head pointer mode is turned off. */
  private sourceBeforeHeadPointer: GazeState['source'] | null = null
  /**
   * Camera tracking drifts as a whole when posture changes (the calibrated shape stays right, the
   * position slides). This offset is added to every camera sample; recenter() sets it, and
   * on-target selections nudge it.
   */
  private offset = { x: 0, y: 0 }
  private rawCapture: ((x: number, y: number, t: number) => void) | null = null
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  subscribeGaze = (listener: () => void): (() => void) => { this.gazeListeners.add(listener); return () => { this.gazeListeners.delete(listener) } }
  getSession = (): SessionState => this.session
  getGaze = (): GazeState => this.gaze
  private publishSession(): void {
    const state = this.client?.getState() ?? this.lastSession
    this.session = { ...state, cameraStatus: this.camera, permissions: state.agentPermissions ? { ...state.agentPermissions, camera: this.camera } : null }
    for (const listener of this.listeners) listener()
  }
  private publishGaze(patch: Partial<GazeState>): void {
    this.gaze = { ...this.gaze, ...patch }
    for (const listener of this.gazeListeners) listener()
  }
  start(): Promise<void> { return this.startup ??= this.initialize() }
  private async initialize(): Promise<void> {
    if (this.disposed) return
    this.bridge = window.gazePlatform
    if (!this.bridge) {
      this.lastSession = { ...this.lastSession, connection: 'error', lastError: { code: 'platform_unavailable', message: 'Open the overlay in Electron to use gaze and the agent.', re: null } }
      this.publishSession()
      return
    }
    try {
      const config = await this.bridge.config()
      if (this.disposed) return
      this.camera = config.camera
      this.publishGaze({ source: fromSetting(config.gazeSource), debug: config.debug || config.gazeSource === 'mouse' })
      if (config.clickMode) this.setClickMode(true)
      try { if (localStorage.getItem(HEAD_POINTER_KEY) === '1') this.setHeadPointer(true) } catch { /* no storage: start in custom calibration */ }
      if (config.demoMode) this.setDemoMode(true)
      this.client = new GazeWsClient({ url: `ws://127.0.0.1:${config.port}/?token=${encodeURIComponent(config.token)}`,
        createSocket: () => new IpcSocket(this.bridge!) })
      this.cleanups.push(this.client.subscribe(state => this.onSession(state, config)))
      this.cleanups.push(this.bridge.onHotkey(event => {
        if (event === 'stop') { this.client?.noteStop(); dwellStore.manager.loseGaze(); dwellStore.publish() }
        else if (event === 'toggle-click') this.setClickMode(!this.gaze.clickMode)
        else if (event === 'toggle-head-pointer') this.setHeadPointer(!this.gaze.headPointer)
        else if (!this.gaze.headPointer) this.setSource(this.gaze.source === 'mouse' ? 'head' : 'mouse')
      }))
      this.cleanups.push(this.bridge.onVisibility(visible => {
        this.visible = visible
        if (!visible) { dwellStore.manager.loseGaze(); dwellStore.publish() }
      }))
      this.cleanups.push(this.bridge.onCursor(sample => { this.cursor = sample }))
      this.cleanups.push(dwellStore.manager.onSelect(event => {
        if (this.gaze.demoMode) playSelectTick(event.id === 'stop')
        // Passive recalibration assumes the pointer was on the card's centre. With magnetic targets it
        // can be up to MAGNET_PX away, so those selections would teach the model wrong positions.
        if (!this.validation.getSnapshot().validating && this.provider instanceof MediaPipeGazeProvider && !this.steady()) {
          this.provider.train(event.center.x, event.center.y)
        }
        if (this.provider instanceof MediaPipeGazeProvider) this.correctDrift(event)
      }))
      this.client.start()
      const permissionsTimer = setInterval(() => { if (this.client?.getState().ready) this.checkPermissions() }, 2000)
      this.cleanups.push(() => clearInterval(permissionsTimer))
      this.switchProvider()
      this.tick()
    } catch (error) {
      this.lastSession = { ...this.lastSession, connection: 'error', lastError: { code: 'platform_failed', message: String(error), re: null } }
      this.publishSession()
    }
  }
  private onSession(state: AgentSession, config: PlatformConfig): void {
    const previous = this.lastSession
    this.lastSession = state
    if (state.settings && state.settings !== this.settings) {
      const first = this.settings === null
      const previousSource = this.settings?.gazeSource
      this.settings = state.settings
      dwellStore.options.dwellMs = state.settings.dwellMs
      if ((first && config.gazeSource !== 'mouse') || (!first && previousSource !== state.settings.gazeSource)) this.setSource(fromSetting(state.settings.gazeSource))
    }
    if (state.connection !== 'open' || state.confirm?.requestId !== previous.confirm?.requestId || state.list?.listId !== previous.list?.listId) {
      dwellStore.manager.loseGaze()
      dwellStore.publish()
    }
    dwellStore.options.connected = state.ready
    this.publishSession()
    this.syncWindow()
    if (state.ready && !previous.ready) this.checkPermissions()
    if (state.refreshTick !== previous.refreshTick && state.mode === 'auto' && !state.task) this.client?.suggestNow()
  }
  private syncWindow(): void {
    const state = this.client?.getState()
    const hover = this.cursor ? document.elementsFromPoint(this.cursor.x, this.cursor.y).some(element => element.closest('[data-caregiver-clickable],button,a[href],input,select,textarea')) : false
    const policy = { taskActive: !!state?.task || !!state?.pendingSelect, confirming: !!state?.confirm && !!state?.ready, caregiverHover: hover }
    if (!this.windowPolicy || Object.keys(policy).some(key => policy[key as keyof WindowPolicy] !== this.windowPolicy![key as keyof WindowPolicy])) {
      this.windowPolicy = policy
      this.bridge?.windowPolicy(policy)
    }
  }
  private tick = (): void => {
    if (this.disposed) return
    const now = performance.now()
    dwellStore.measure()
    if (this.visible && !this.validation.getSnapshot().validating && this.latest && now - this.latest.t < 250 && this.latest.confidence > 0) {
      // Advance once per frame, never indefinitely at a stale gaze point.
      dwellStore.manager.update({ x: this.latest.x, y: this.latest.y, t: now })
    } else {
      dwellStore.manager.loseGaze()
      if (this.gaze.point) this.publishGaze({ point: null, confidence: 0 })
    }
    dwellStore.publish()
    this.syncWindow()
    this.frame = requestAnimationFrame(this.tick)
  }
  private sample = (sample: GazeSample): void => {
    if (!Number.isFinite(sample.x) || !Number.isFinite(sample.y) || sample.confidence <= 0) {
      this.latest = null
      this.filter.reset()
      this.publishGaze({ point: null, confidence: 0 })
      return
    }
    const t = performance.now()
    if (this.latest && t - this.latest.t > 250) this.filter.reset()
    this.rawCapture?.(sample.x, sample.y, t)
    const camera = this.provider instanceof MediaPipeGazeProvider
    const x = camera ? sample.x + this.offset.x : sample.x, y = camera ? sample.y + this.offset.y : sample.y
    this.validation.sample({ ...sample, x, y, t }) // held-out error uses raw prediction, not a filtered dot
    const point = this.filter.filter(x, y, t)
    this.latest = { ...point, t, confidence: sample.confidence }
    this.publishGaze({ point, confidence: sample.confidence })
  }
  quit(): void { this.bridge?.quit() }
  /** On-target selections pull the offset toward the target centre (magnet-held ones don't count). */
  private correctDrift(event: { center: { x: number; y: number }; rect?: { x: number; y: number; w: number; h: number } }): void {
    const p = this.latest, r = event.rect
    if (!p || !r || this.validation.getSnapshot().validating) return
    if (p.x < r.x || p.x > r.x + r.w || p.y < r.y || p.y > r.y + r.h) return
    const clamp = (v: number) => Math.max(-MAX_OFFSET_PX, Math.min(MAX_OFFSET_PX, v))
    this.offset = { x: clamp(this.offset.x + DRIFT_GAIN * (event.center.x - p.x)), y: clamp(this.offset.y + DRIFT_GAIN * (event.center.y - p.y)) }
  }
  /** Re-zero the drift offset: the user points at (x, y); raw samples after settleMs are averaged. */
  async recenter(x: number, y: number, settleMs = 1200, measureMs = 1500): Promise<{ x: number; y: number }> {
    if (!(this.provider instanceof MediaPipeGazeProvider)) throw new Error('Recenter needs camera tracking')
    const start = performance.now()
    const xs: number[] = [], ys: number[] = []
    this.rawCapture = (sx, sy, t) => { if (t - start >= settleMs) { xs.push(sx); ys.push(sy) } }
    try { await new Promise<void>(resolve => setTimeout(resolve, settleMs + measureMs)) } finally { this.rawCapture = null }
    if (!xs.length) throw new Error('No tracking samples; check that the camera sees your face')
    const mean = (v: number[]) => v.reduce((a, b) => a + b, 0) / v.length
    this.offset = { x: Math.max(-MAX_OFFSET_PX, Math.min(MAX_OFFSET_PX, x - mean(xs))), y: Math.max(-MAX_OFFSET_PX, Math.min(MAX_OFFSET_PX, y - mean(ys))) }
    return this.offset
  }
  /** macOS Head Pointer moves the system cursor, so the pointer source is the mouse while it is on;
   *  turning it off returns to the calibrated source used before. Remembered across launches. */
  setHeadPointer(on: boolean): void {
    if (on === this.gaze.headPointer) return
    try { localStorage.setItem(HEAD_POINTER_KEY, on ? '1' : '0') } catch { /* private mode: session only */ }
    this.publishGaze({ headPointer: on })
    if (on) { this.sourceBeforeHeadPointer = this.gaze.source; this.setSource('mouse') }
    else if (this.sourceBeforeHeadPointer) { this.setSource(this.sourceBeforeHeadPointer); this.sourceBeforeHeadPointer = null }
    this.applyPointerMode()
  }
  /** Head pointer mode (or head pose as the source): steadier smoothing and magnetic targets. */
  private steady(): boolean { return this.gaze.headPointer || this.gaze.source === 'head' }
  private applyPointerMode(): void {
    const steady = this.steady()
    this.filter = steady ? new PointFilter(STEADY_ONE_EURO) : new PointFilter()
    dwellStore.manager.setMagnet(steady ? MAGNET_PX : 0)
  }
  setDemoMode(on: boolean): void {
    this.publishGaze({ demoMode: on })
  }
  setClickMode(on: boolean): void {
    dwellStore.options.clickMode = on
    dwellStore.manager.setDwellEnabled(!on)
    dwellStore.publish()
    this.publishGaze({ clickMode: on })
  }
  setSource(source: GazeState['source']): void {
    if (source === this.gaze.source) return
    this.publishGaze({ source, point: null, confidence: 0, debug: source === 'mouse', error: null })
    this.applyPointerMode()
    this.switchProvider()
  }
  private switchProvider(): void {
    this.providerJob = this.providerJob.then(async () => {
      this.providerOff?.(); this.providerOff = null
      this.provider?.stop(); this.provider = null
      this.latest = null; this.filter.reset(); dwellStore.manager.loseGaze(); dwellStore.publish()
      if (this.disposed || !this.bridge || (this.gaze.source !== 'mouse' && !this.cameraReady)) return
      const source = this.gaze.source
      const provider = source === 'mouse' ? new MouseGazeProvider(this.bridge) : this.cameraProvider(source)
      this.provider = provider
      this.providerOff = provider.onSample(this.sample)
      await provider.start()
      if (this.disposed) { provider.stop(); return }
      this.publishGaze({ error: null })
    }).catch(error => { this.publishGaze({ error: describeError(error), point: null, confidence: 0 }) })
  }
  private cameraProvider(source: 'webgazer' | 'head'): MediaPipeGazeProvider {
    let provider = this.cameraProviders.get(source)
    if (!provider) {
      provider = source === 'head' ? new HeadPoseProvider() : new MediaPipeGazeProvider()
      try {
        const saved = localStorage.getItem(calibrationKey(source))
        if (saved) provider.restoreTraining(JSON.parse(saved))
      } catch { /* no storage or a corrupt entry: calibrate again */ }
      this.cameraProviders.set(source, provider)
    }
    return provider
  }
  /** Whether switching to this camera source can skip calibration (calibrated now or in an earlier launch). */
  isTrained(source: 'webgazer' | 'head'): boolean { return this.cameraProvider(source).trained }
  /** Saves the current camera source's calibration for later launches (after a finished calibration). */
  saveCalibration(): void {
    const source = this.gaze.source
    if (source === 'mouse' || !this.cameraProviders.get(source)?.trained) return
    try { localStorage.setItem(calibrationKey(source), JSON.stringify(this.cameraProviders.get(source)!.training)) } catch { /* full or private: this launch only */ }
  }
  /** Starts the camera for eye tracking (webgazer) or head pose (head) and switches to it. */
  async startCalibration(target: 'webgazer' | 'head' = 'webgazer'): Promise<void> {
    await this.start()
    const camera = await this.bridge?.cameraStatus(true)
    if (!camera) throw new Error('Camera bridge unavailable')
    this.camera = camera; this.publishSession()
    if (camera !== 'granted' && camera !== 'unknown') throw new Error(`Camera permission is ${camera}`)
    this.cameraReady = true
    this.cameraProviders.delete(target) // a calibration always trains a fresh model
    if (this.gaze.source !== target) this.setSource(target)
    else this.switchProvider()
    await this.providerJob
    if (!(this.provider instanceof MediaPipeGazeProvider) || this.gaze.error) throw new Error(this.gaze.error ?? 'Camera tracking could not start')
    this.provider.startRecording()
    this.offset = { x: 0, y: 0 } // a fresh calibration defines its own zero
    const log: CalibrationLog = { target, startedAt: new Date().toISOString(), trains: [], checkDots: [] }
    this.calibrationLog = log
    let lastPoint: unknown = null
    const off = this.validation.subscribe(() => {
      const v = this.validation.getSnapshot()
      if (this.calibrationLog !== log) { off(); return }
      if (v.validationPoint && v.validationPoint !== lastPoint) log.checkDots.push({ t: Math.round(performance.now()), index: v.pointIndex, ...v.validationPoint })
      lastPoint = v.validationPoint
    })
  }
  train(x: number, y: number): void {
    if (!this.validation.getSnapshot().validating && Number.isFinite(x) && Number.isFinite(y) && this.provider instanceof MediaPipeGazeProvider) {
      this.provider.train(x, y)
      this.calibrationLog?.trains.push({ t: Math.round(performance.now()), x, y })
    }
  }
  /**
   * Debug: writes the last calibration (raw per-frame signals, training and check dots with times,
   * plus `extra` such as the result) to <repo>/.debug/ for offline tuning. Resolves to the path.
   */
  async exportCalibration(extra: Record<string, unknown> = {}): Promise<string | null> {
    const log = this.calibrationLog
    if (!log || !this.bridge || !(this.provider instanceof MediaPipeGazeProvider)) return null
    this.calibrationLog = null
    const frames = this.provider.takeRecording()
    const stamp = log.startedAt.replace(/[:.]/g, '-').replace('T', '-').slice(0, 19).toLowerCase()
    const data = { version: 1, ...log, screen: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio }, ...extra, frames }
    return this.bridge.saveDebug(`calibration-${log.target}-${stamp}.json`, JSON.stringify(data))
  }
  setMode(mode: 'auto' | 'type'): void { if (!this.client?.getState().task) { this.client?.resetLocal(); this.client?.setMode(mode) } }
  suggestNow(): void { this.client?.suggestNow() }
  setDockIdle(idle: boolean): void { this.client?.send('gaze_context', { dock_idle: idle, idle_ms: idle ? 1500 : 0 }) }
  decode(words: string[], rawKeys: string[]): void {
    this.client?.send('decode_request', { words, raw_keys: rawKeys.length ? [rawKeys as [string, ...string[]]] : [] })
  }
  submitIntent(text: string): void { if (text.trim()) { this.client?.resetLocal(); this.client?.send('intent_submit', { text }) } }
  selectPlan(listId: string, planId: string): boolean {
    const state = this.client?.getState()
    if (!state || state.list?.listId !== listId) return false
    if (planId === 'other') { this.client?.resetLocal(); this.client?.setMode('type'); return true }
    if (planId === 'recovery:cancel') { this.client?.resetLocal(); return true }
    return this.client?.selectPlan(listId, planId) ?? false
  }
  respondChoice(choiceId: string | null): boolean { return this.client?.respondChoice(choiceId) ?? false }
  respondConfirm(confirmed: boolean): boolean { return this.client?.respondConfirm(confirmed) ?? false }
  stop(reason: 'gaze' | 'hotkey'): boolean { return this.client?.sendStop(reason) ?? false }
  getProfile(): void { this.client?.send('profile_get', {}) }
  updateProfile(patch: object): void { this.client?.send('profile_update', { patch }) }
  updateSettings(patch: object): void { this.client?.send('settings_update', { patch }) }
  checkPermissions(): void {
    this.client?.send('permissions_check', {})
    void this.bridge?.cameraStatus().then(status => { this.camera = status; this.publishSession() })
  }
  openSettingsPane(pane: 'accessibility' | 'screen_recording' | 'camera'): void {
    if (pane === 'camera') void this.bridge?.cameraStatus(true).then(status => { this.camera = status; this.publishSession() })
    else this.client?.send('open_settings_pane', { pane })
  }
  dispose(): void {
    this.disposed = true; cancelAnimationFrame(this.frame)
    for (const cleanup of this.cleanups) cleanup()
    this.providerOff?.(); this.provider?.stop(); this.client?.stop()
  }
}
export const runtime = new PlatformRuntime()
