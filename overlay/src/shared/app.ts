export const APP_NAME = 'Gaze Copilot'
export const APP_VERSION = '0.1.0'
export type CameraStatus = 'not-determined' | 'granted' | 'denied' | 'restricted' | 'unknown'
export type GazeSource = 'webgazer' | 'mouse'
export interface CursorSample { x: number; y: number; t: number }
export interface PlatformConfig { port: number; token: string; gazeSource: GazeSource; debug: boolean; camera: CameraStatus }
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
  onHotkey(listener: (event: 'stop' | 'toggle-source') => void): () => void
  onVisibility(listener: (visible: boolean) => void): () => void
  cameraStatus(request?: boolean): Promise<CameraStatus>
  windowPolicy(policy: WindowPolicy): void
  connect(id: string): void
  send(id: string, data: string): void
  close(id: string): void
  onTransport(listener: (event: TransportEvent) => void): () => void
}
declare global { interface Window { gazePlatform?: PlatformBridge } }
