// Test double for '../platform' (the A1/A2 interface). Use from a *.test.ts file with:
//   vi.mock('../platform', async () => (await import('../dock/test-platform')).platformMock)
// <DwellTarget> renders a plain element and records its props; `dwell(id)` completes a dwell.
import { createElement, useSyncExternalStore } from 'react'
import { vi } from 'vitest'
import type { CalibrationState, DwellTargetProps, GazeState, Plan, SessionState } from '../platform'

export const baseSession = (patch: Partial<SessionState> = {}): SessionState => ({
  suggestPending: false,
  suggestRequest: null,
  stopping: false,
  connection: 'open',
  closeCode: null,
  ready: true,
  mode: 'auto',
  demoMode: false,
  profile: null,
  settings: { dwellMs: 800, blinkSelect: false, density: 'large', gazeSource: 'mouse', calibrationMode: 'gaze' },
  agentPermissions: { accessibility: true, screen_recording: true, camera: 'unknown' },
  list: null,
  sentences: null,
  task: null,
  choice: null,
  confirm: null,
  result: null,
  pendingSelect: null,
  lastError: null,
  refreshTick: 0,
  cameraStatus: 'granted',
  permissions: { accessibility: true, screen_recording: true, camera: 'granted' },
  ...patch
})

export const plan = (id: string, label: string, extra: Partial<Plan> = {}): Plan =>
  ({ id, label, kind: 'task', risky: false, ...extra })

let session = baseSession()
const baseGaze = (): GazeState => ({ source: 'mouse', point: null, confidence: 0, debug: false, error: null })
const baseCalibration = (): CalibrationState => ({ validating: false, validationPoint: null, pointIndex: 0, error: null })
let gaze = baseGaze()
let calibrationState = baseCalibration()
const listeners = new Set<() => void>()
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
const notify = () => { for (const listener of listeners) listener() }

export const targets = new Map<string, DwellTargetProps>()

export const agent = {
  setMode: vi.fn(),
  suggestNow: vi.fn(),
  setDockIdle: vi.fn(),
  decode: vi.fn(),
  submitIntent: vi.fn(),
  selectPlan: vi.fn(() => true),
  respondChoice: vi.fn(() => true),
  respondConfirm: vi.fn(() => true),
  stop: vi.fn(() => true),
  getProfile: vi.fn(),
  updateProfile: vi.fn(),
  updateSettings: vi.fn(),
  checkPermissions: vi.fn(),
  openSettingsPane: vi.fn()
}

export const calibration = {
  start: vi.fn(async () => {}),
  train: vi.fn(),
  validate: vi.fn(async (_points: { x: number; y: number }[]) => ({ meanErrorPx: 120 }))
}

export const platformMock = {
  DwellTarget: (props: DwellTargetProps) => {
    targets.set(props.id, props)
    return createElement('div', {
      'data-dwell-id': props.id, 'data-variant': props.variant, 'aria-disabled': props.disabled || undefined,
      className: props.className
    }, props.children)
  },
  useSession: () => useSyncExternalStore(subscribe, () => session),
  useGaze: () => useSyncExternalStore(subscribe, () => gaze),
  useCalibration: () => useSyncExternalStore(subscribe, () => calibrationState),
  setGazeSource: vi.fn(),
  calibration,
  agent
}

/** Replace part of the session and re-render subscribers (call inside act()). */
export function setSession(patch: Partial<SessionState>): void {
  session = { ...session, ...patch }
  notify()
}

export function setGaze(patch: Partial<GazeState>): void {
  gaze = { ...gaze, ...patch }
  notify()
}

export function setCalibrationState(patch: Partial<CalibrationState>): void {
  calibrationState = { ...calibrationState, ...patch }
  notify()
}

export function resetPlatform(patch: Partial<SessionState> = {}): void {
  session = baseSession(patch)
  gaze = baseGaze()
  calibrationState = baseCalibration()
  targets.clear()
  for (const fn of [...Object.values(agent), ...Object.values(calibration), platformMock.setGazeSource]) fn.mockClear()
}

export const mounted = (id: string): HTMLElement | null =>
  [...document.querySelectorAll<HTMLElement>('[data-dwell-id]')].find(el => el.dataset.dwellId === id) ?? null

/** Ids of the mounted targets, in document order. */
export const targetIds = (): string[] =>
  [...document.querySelectorAll<HTMLElement>('[data-dwell-id]')].map(el => el.dataset.dwellId!)

/** A completed dwell on a mounted target. Disabled targets never select, as in the platform. */
export function dwell(id: string): boolean {
  const props = targets.get(id)
  if (!props || !mounted(id)) throw new Error(`no mounted target ${id}`)
  if (props.disabled) return false
  props.onSelect()
  return true
}
