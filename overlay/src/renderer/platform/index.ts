/** Stable A1/A2 surface. UI imports platform only; visuals belong to A1. */
import { createElement, useEffect, useRef, useState, useSyncExternalStore, type ReactNode, type JSX } from 'react'
import { DwellManager, confirmDwellMs, type DwellVariant } from '../dwell/DwellManager'
import { initialSession, type SessionState } from '../ws/session'
export type { SessionState } from '../ws/session'
export type { Plan, Profile, Settings, ChoiceOption } from '../ws/protocol.gen'

export interface DwellTargetProps {
  id: string
  variant: DwellVariant
  dwellMs?: number
  hitPadding?: number
  disabled?: boolean
  onSelect: () => void
  className?: string
  children: ReactNode
}
export interface GazeState {
  source: 'webgazer' | 'mouse'
  point: { x: number; y: number } | null
  confidence: number
  debug: boolean
}
const manager = new DwellManager()
const listeners = new Set<() => void>()
let session = initialSession()
let gaze: GazeState = { source: 'mouse', point: null, confidence: 0, debug: true }
const notify = () => { for (const listener of listeners) listener() }
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }

export function DwellTarget(props: DwellTargetProps): JSX.Element {
  const element = useRef<HTMLDivElement>(null)
  const select = useRef(props.onSelect)
  select.current = props.onSelect
  const [, render] = useState(0)
  useEffect(() => {
    const update = () => {
      const r = element.current?.getBoundingClientRect()
      if (!r) return
      manager.register({ id: props.id, variant: props.variant, disabled: props.disabled,
        rect: { x: r.x, y: r.y, w: r.width, h: r.height }, hitPadding: props.hitPadding,
        dwellMs: props.variant === 'stop' ? 400 : props.variant === 'confirm' ? confirmDwellMs(props.dwellMs ?? 800) : props.dwellMs ?? 800,
        onSelect: () => select.current() })
      render(n => n + 1)
    }
    update()
    const off = subscribe(update)
    return () => { off(); manager.unregister(props.id) }
  }, [props.id, props.variant, props.disabled, props.dwellMs, props.hitPadding])
  const state = manager.getState()
  const progress = manager.progressOf(props.id)
  const status = state.lastSelect?.id === props.id && state.locked ? 'selected' : state.locked && props.variant !== 'stop' ? 'cooldown' : state.activeId === props.id ? 'active' : 'idle'
  return createElement('div', { ref: element, className: props.className, 'data-dwell': status,
    'aria-disabled': props.disabled || undefined, style: { '--dwell-progress': progress } }, props.children)
}
export function useGaze(): GazeState { return useSyncExternalStore(subscribe, () => gaze) }
export function setGazeSource(source: GazeState['source']): void { gaze = { ...gaze, source, point: null, confidence: 0 }; notify() }
export const calibration = {
  async start(): Promise<void> {},
  train(_x: number, _y: number): void {},
  async validate(_points: { x: number; y: number }[]): Promise<{ meanErrorPx: number }> { return { meanErrorPx: 0 } }
}
export function useSession(): SessionState { return useSyncExternalStore(subscribe, () => session) }
export const agent = {
  setMode(mode: 'auto' | 'type'): void { session = { ...session, mode }; notify() },
  suggestNow(): void {},
  setDockIdle(_idle: boolean): void {},
  decode(_words: string[], _rawKeys: string[]): void {},
  submitIntent(_text: string): void {},
  selectPlan(_listId: string, _planId: string): boolean { return false },
  respondChoice(_choiceId: string | null): boolean { return false },
  respondConfirm(_confirmed: boolean): boolean { return false },
  stop(_reason: 'gaze' | 'hotkey'): boolean { return false },
  getProfile(): void {},
  updateProfile(_patch: object): void {},
  updateSettings(_patch: object): void {},
  checkPermissions(): void {},
  openSettingsPane(_pane: 'accessibility' | 'screen_recording' | 'camera'): void {}
}
// Temporary browser mouse implementation; the real provider uses main-process cursor IPC.
if (typeof window !== 'undefined') window.addEventListener('mousemove', event => {
  gaze = { ...gaze, point: { x: event.clientX, y: event.clientY }, confidence: 1 }
  notify()
})
if (typeof window !== 'undefined') {
  const tick = () => { if (gaze.point) { manager.update({ ...gaze.point, t: performance.now() }); notify() }; requestAnimationFrame(tick) }
  requestAnimationFrame(tick)
}
