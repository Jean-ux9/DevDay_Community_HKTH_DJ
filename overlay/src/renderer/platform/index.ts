/** Stable A1/A2 surface. No UI should import the implementation modules. */
import { createElement, useEffect, useSyncExternalStore, type JSX } from 'react'
import { DwellTarget as Target, type DwellTargetProps } from '../dwell/DwellTarget'
import { runtime, type GazeState, type SessionState } from './runtime'
import type { ValidationResult } from '../gaze/calibration'
export type { DwellTargetProps } from '../dwell/DwellTarget'
export type { GazeState, SessionState } from './runtime'
export type { CalibrationState, ValidationResult } from '../gaze/calibration'
export type { Plan, Profile, Settings, ChoiceOption } from '../ws/protocol.gen'
const usePlatform = (): void => { useEffect(() => { void runtime.start() }, []) }
export function DwellTarget(props: DwellTargetProps): JSX.Element { usePlatform(); return createElement(Target, props) }
export function useGaze(): GazeState { usePlatform(); return useSyncExternalStore(runtime.subscribeGaze, runtime.getGaze) }
export function setGazeSource(source: 'webgazer' | 'mouse' | 'head'): void { runtime.setSource(source) }
/** Click mode on: real clicks select and dwell is off (STOP keeps its dwell). Hotkey ⌃⌥⌘D toggles it. */
export function setClickMode(on: boolean): void { runtime.setClickMode(on) }
/** Head pointer mode: steadier pointer smoothing; the UI pulls targets in from the edges. */
export function setHeadPointer(on: boolean): void { runtime.setHeadPointer(on) }
/** Quits the whole app (Electron and the agent). Hotkey ⌃⌥⌘Q. */
export function quitApp(): void { runtime.quit() }
export function useSession(): SessionState { usePlatform(); return useSyncExternalStore(runtime.subscribe, runtime.getSession) }
/** A1 renders validationPoint while validate(points) walks the four validation dots. */
export function useCalibration() { usePlatform(); return useSyncExternalStore(runtime.validation.subscribe, runtime.validation.getSnapshot) }
export const calibration = {
  /** Camera on and tracking switched to eye tracking (default) or head pose. */
  start: (target: 'webgazer' | 'head' = 'webgazer'): Promise<void> => runtime.startCalibration(target),
  train: (x: number, y: number): void => runtime.train(x, y),
  validate: (points: { x: number; y: number }[], timing?: { settleMs?: number; measureMs?: number }): Promise<ValidationResult> =>
    runtime.validation.validate(points, timing),
  /** Re-zeros camera-tracking drift: the user points at (x, y) for settle + measure ms. Resolves to the offset. */
  recenter: (x: number, y: number, settleMs?: number, measureMs?: number): Promise<{ x: number; y: number }> => runtime.recenter(x, y, settleMs, measureMs),
  /** Debug: saves the last calibration's raw data to <repo>/.debug/ (Electron only). Resolves to the path. */
  exportLog: (extra?: Record<string, unknown>): Promise<string | null> => runtime.exportCalibration(extra)
}
export const agent = {
  setMode: (mode: 'auto' | 'type'): void => runtime.setMode(mode),
  suggestNow: (): void => runtime.suggestNow(),
  setDockIdle: (idle: boolean): void => runtime.setDockIdle(idle),
  decode: (words: string[], rawKeys: string[]): void => runtime.decode(words, rawKeys),
  submitIntent: (text: string): void => runtime.submitIntent(text),
  selectPlan: (listId: string, planId: string): boolean => runtime.selectPlan(listId, planId),
  respondChoice: (choiceId: string | null): boolean => runtime.respondChoice(choiceId),
  respondConfirm: (confirmed: boolean): boolean => runtime.respondConfirm(confirmed),
  stop: (reason: 'gaze' | 'hotkey'): boolean => runtime.stop(reason),
  getProfile: (): void => runtime.getProfile(),
  updateProfile: (patch: object): void => runtime.updateProfile(patch),
  updateSettings: (patch: object): void => runtime.updateSettings(patch),
  checkPermissions: (): void => runtime.checkPermissions(),
  openSettingsPane: (pane: 'accessibility' | 'screen_recording' | 'camera'): void => runtime.openSettingsPane(pane)
}
