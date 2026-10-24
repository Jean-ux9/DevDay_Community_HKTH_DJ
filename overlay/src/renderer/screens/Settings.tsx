// Settings (spec §5.2, §5.3, §10): dwell time, gaze source, text size, blink select, calibration
// helper, and "Recalibrate". Values shown come only from settings_result (the session), never
// from local guesses.
import type { JSX } from 'react'
import { DwellTarget, agent, quitApp, setClickMode, setHeadPointer, setGazeSource, useGaze, useSession, type Settings as SettingsValue } from '../platform'
import { Card, InfoPanel } from '../dock/Card'
import { CheckIcon, CloseIcon, RetryIcon, SlidersIcon } from '../dock/icons'
import { lastCalibrationErrorPx } from './Calibration'

/** Head pointer mode is overlay-local (the agent's settings schema is frozen): kept in localStorage. */
const HEAD_POINTER_KEY = 'gaze.headPointer'
export const savedHeadPointer = (): boolean => { try { return localStorage.getItem(HEAD_POINTER_KEY) === '1' } catch { return false } }
export function toggleHeadPointer(on: boolean): void {
  setHeadPointer(on)
  try { localStorage.setItem(HEAD_POINTER_KEY, on ? '1' : '0') } catch { /* private mode: session only */ }
}

export const DWELL_MIN_MS = 500
export const DWELL_MAX_MS = 2000
export const DWELL_STEP_MS = 100
/** Rarely needed and top-left, where people read: a slower dwell avoids opening it by accident. */
export const SETTINGS_DWELL_MS = 1500

const clamp = (ms: number) => Math.min(DWELL_MAX_MS, Math.max(DWELL_MIN_MS, ms))

/** The pointer sources in the order the Settings card cycles through them. */
const SOURCES = ['mouse', 'head', 'webgazer'] as const
const SOURCE_NAMES = { mouse: 'mouse', head: 'head pose', webgazer: 'eye tracking' } as const

export function SettingsPanel({ onRecalibrate, onClose }:
  { onRecalibrate: (target: 'webgazer' | 'head') => void; onClose: () => void }): JSX.Element {
  const s = useSession()
  const gaze = useGaze()
  const settings = s.settings
  if (!settings) {
    return <InfoPanel><span className="info-title">Waiting for the agent…</span></InfoPanel>
  }
  const update = (patch: Partial<SettingsValue>) => agent.updateSettings(patch)
  const source = gaze.source
  return (
    <div className="dock-section">
      <h2 className="dock-question">Settings</h2>
      <div className="card-row settings-grid">
        <InfoPanel className="value-panel">
          <span className="info-title">Dwell time</span>
          <span className="value-big">{settings.dwellMs} ms</span>
        </InfoPanel>
        <Card id="set-dwell-faster" label="Faster" detail={`−${DWELL_STEP_MS} ms`} clickable
          disabled={settings.dwellMs <= DWELL_MIN_MS} onSelect={() => update({ dwellMs: clamp(settings.dwellMs - DWELL_STEP_MS) })} />
        <Card id="set-dwell-slower" label="Slower" detail={`+${DWELL_STEP_MS} ms`} clickable
          disabled={settings.dwellMs >= DWELL_MAX_MS} onSelect={() => update({ dwellMs: clamp(settings.dwellMs + DWELL_STEP_MS) })} />
        <Card id="set-source" label={`Pointer: ${SOURCE_NAMES[source]}`}
          detail={`Switch to ${SOURCE_NAMES[SOURCES[(SOURCES.indexOf(source) + 1) % SOURCES.length]!]} (⌃⌥⌘M)`} clickable
          onSelect={() => {
            const next = SOURCES[(SOURCES.indexOf(source) + 1) % SOURCES.length]!
            if (next === 'mouse') { setGazeSource('mouse'); update({ gazeSource: 'mouse' }) }
            else onRecalibrate(next) // camera tracking needs calibration before it can be used
          }} />
        <Card id="set-click-mode" label={gaze.clickMode ? 'Select: by clicking' : 'Select: by resting on it'}
          detail={gaze.clickMode ? 'Resting does nothing; STOP still works (⌃⌥⌘D)' : 'Switch to real clicks (⌃⌥⌘D)'} clickable
          onSelect={() => setClickMode(!gaze.clickMode)} />
        <Card id="set-head-pointer" label={gaze.headPointer ? 'Head pointer: on' : 'Head pointer: off'}
          detail={gaze.source === 'head' ? 'Always on with head pose' : 'For macOS Head Pointer: steadier, magnetic'} clickable
          onSelect={() => toggleHeadPointer(!gaze.headPointer)} />
        <Card id="set-density" label={settings.density === 'large' ? 'Text: large' : 'Text: compact'}
          detail={settings.density === 'large' ? 'Switch to compact' : 'Switch to large'} clickable
          onSelect={() => update({ density: settings.density === 'large' ? 'compact' : 'large' })} />
        <Card id="set-blink" label={settings.blinkSelect ? 'Blink select: on' : 'Blink select: off'}
          detail="A long blink selects" clickable onSelect={() => update({ blinkSelect: !settings.blinkSelect })} />
        <Card id="set-calib-mode" label={settings.calibrationMode === 'caregiver' ? 'Calibrate: with helper' : 'Calibrate: gaze only'}
          detail="How the dots are recorded" clickable
          onSelect={() => update({ calibrationMode: settings.calibrationMode === 'caregiver' ? 'gaze' : 'caregiver' })} />
        <Card id="set-recalibrate" label="Recalibrate"
          detail={lastCalibrationErrorPx === null ? 'Run the dots again' : `Last error: ${Math.round(lastCalibrationErrorPx)} px`} icon={<RetryIcon />} clickable onSelect={() => onRecalibrate(source === 'webgazer' ? 'webgazer' : 'head')} />
        <Card id="set-close" label="Done" detail="Back to the dock" icon={<CheckIcon />} clickable onSelect={onClose} />
      </div>
    </div>
  )
}

/** Quitting is final: a real click, or a deliberately long dwell. */
export const QUIT_DWELL_MS = 2000

export function QuitCorner(): JSX.Element {
  return (
    <DwellTarget id="quit-app" variant="card" dwellMs={QUIT_DWELL_MS} clickable onSelect={quitApp}
      className="target settings-corner quit-corner">
      <span className="card-icon"><CloseIcon /></span>
      <span className="settings-corner-label">Quit</span>
    </DwellTarget>
  )
}

/** The way into Settings: top-left corner, mirroring STOP, only while idle. */
export function SettingsCorner({ onSelect }: { onSelect: () => void }): JSX.Element {
  return (
    <DwellTarget id="settings-open" variant="card" dwellMs={SETTINGS_DWELL_MS} clickable onSelect={onSelect}
      className="target settings-corner">
      <span className="card-icon"><SlidersIcon /></span>
      <span className="settings-corner-label">Settings</span>
    </DwellTarget>
  )
}
