export const APP_NAME = 'Gaze Copilot'
export const APP_VERSION = '0.1.0'
export type CameraStatus = 'not-determined' | 'granted' | 'denied' | 'restricted' | 'unknown'
export type GazeSource = 'webgazer' | 'mouse'
export interface CursorSample { x: number; y: number; t: number }
export interface PlatformConfig { port: number; token: string; gazeSource: GazeSource; debug: boolean; camera: CameraStatus
  /** Start in click mode (GAZE_CLICK_MODE=1): targets select on a real click, only STOP on dwell. */
  clickMode?: boolean
  /** Developers only: start in demo mode (GAZE_DEMO_UI=1; ?demo=1 in the browser preview). */
  demoMode?: boolean }
export type HotkeyEvent = 'stop' | 'toggle-source' | 'toggle-click' | 'toggle-head-pointer'
export interface WindowPolicy { taskActive: boolean; confirming: boolean; caregiverHover: boolean }
export type TransportEvent = { id: string } & (
  | { type: 'open' }
  | { type: 'message'; data: string }
  | { type: 'close'; code: number; reason: string }
)
/** Narrow preload contract: no generic IPC, filesystem, shell or desktop-action access. */
export interface PlatformBridge {
  config(): Promise<PlatformConfig>
  onCursor(listener: (sample: CursorSample) => void): () => void
  onHotkey(listener: (event: HotkeyEvent) => void): () => void
  onVisibility(listener: (visible: boolean) => void): () => void
  cameraStatus(request?: boolean): Promise<CameraStatus>
  windowPolicy(policy: WindowPolicy): void
  /** Quits the app (and the agent it spawned). */
  quit(): void
  /** Debug only: writes JSON to <repo>/.debug/<name> (git-ignored). Resolves to the path, or null. */
  saveDebug(name: string, json: string): Promise<string | null>
  connect(id: string): void
  send(id: string, data: string): void
  close(id: string): void
  onTransport(listener: (event: TransportEvent) => void): () => void
}
declare global { interface Window { gazePlatform?: PlatformBridge } }
