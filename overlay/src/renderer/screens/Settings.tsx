// Settings (spec §5.2, §5.3, §10): dwell time, gaze source, text size, calibration
// helper, and "Recalibrate". Values shown come only from settings_result (the session), never
// from local guesses. Two pointer modes: custom calibration (default) shows the calibration cards;
// macOS Head Pointer mode (⌘⌥P) hides them, since the system moves the cursor.
import type { JSX } from 'react'
import { agent, isPointerTrained, quitApp, setClickMode, setHeadPointer, setGazeSource, useGaze, useSession, type Settings as SettingsValue } from '../platform'
import { Card, InfoPanel } from '../dock/Card'
import { CloseIcon, GearIcon, RetryIcon } from '../dock/icons'
import { CornerTarget } from '../dock/CornerTarget'
import { lastCalibrationErrorPx } from './Calibration'

export const DWELL_MIN_MS = 500
export const DWELL_MAX_MS = 2000
export const DWELL_STEP_MS = 100
/** Rarely needed and top-left, where people read: a slower dwell avoids opening it by accident. */
export const SETTINGS_DWELL_MS = 1500

const clamp = (ms: number) => Math.min(DWELL_MAX_MS, Math.max(DWELL_MIN_MS, ms))

const SOURCE_NAMES = { mouse: 'mouse', head: 'head tracking', webgazer: 'eye tracking' } as const

/** No Done card: STOP leaves Settings, the same way in both pointer modes. */
export function SettingsPanel({ onRecalibrate, onRecenter }:
  { onRecalibrate: (target: 'webgazer' | 'head') => void; onRecenter?: () => void }): JSX.Element {
  const s = useSession()
  const gaze = useGaze()
  const settings = s.settings
  if (!settings) {
    return <InfoPanel><span className="info-title">Waiting for the agent…</span></InfoPanel>
  }
  const update = (patch: Partial<SettingsValue>) => agent.updateSettings(patch)
  const source = gaze.source
  // The card toggles mouse <-> head tracking. The calibration is saved, so only the very first switch calibrates.
  const nextSource = source === 'mouse' ? 'head' : 'mouse'
  const needsCalibration = nextSource === 'head' && !isPointerTrained('head')
  const headPointer = gaze.headPointer
  // Shortcut hints help while developing; in demo mode the audience doesn't need them.
  const keys = (hint: string) => gaze.demoMode ? '' : ` (${hint})`
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
        {/* Same spot in both modes: the cards that follow change with the mode. */}
        <Card id="set-head-pointer" label={headPointer ? 'Mode: macOS Head Pointer' : 'Mode: custom calibration'}
          detail={(headPointer ? 'Back to custom calibration' : 'Use macOS Head Pointer') + keys('⌘⌥P')} clickable
          onSelect={() => setHeadPointer(!headPointer)} />
        {!headPointer && <Card id="set-source" label={`Pointer: ${SOURCE_NAMES[source]}`}
          detail={`Switch to ${SOURCE_NAMES[nextSource]}${needsCalibration ? ', calibrates first' : ''}${keys('⌃⌥⌘M')}`} clickable
          onSelect={() => {
            if (needsCalibration) { onRecalibrate('head'); return }
            setGazeSource(nextSource)
            update({ gazeSource: nextSource === 'mouse' ? 'mouse' : 'webgazer' }) // 'webgazer' = camera pointer
          }} />}
        <Card id="set-click-mode" label={gaze.clickMode ? 'Select: by clicking' : 'Select: by resting on it'}
          detail={(gaze.clickMode ? 'STOP still works by resting' : 'Use real clicks') + keys('⌃⌥⌘D')} clickable
          onSelect={() => setClickMode(!gaze.clickMode)} />
        <Card id="set-density" label={settings.density === 'large' ? 'Text: large' : 'Text: compact'}
          detail={settings.density === 'large' ? 'Make it compact' : 'Make it large'} clickable
          onSelect={() => update({ density: settings.density === 'large' ? 'compact' : 'large' })} />
        {!headPointer && <Card id="set-recalibrate" label="Recalibrate"
          detail={lastCalibrationErrorPx === null ? 'Run the dots again' : `Last: ${Math.round(lastCalibrationErrorPx)} px off`} icon={<RetryIcon />} clickable onSelect={() => onRecalibrate(source === 'webgazer' ? 'webgazer' : 'head')} />}
        {!headPointer && source !== 'mouse' && onRecenter && (
          <Card id="set-recenter" label="Recenter pointer" detail="Pointer off? Look at one dot for 3 s" icon={<RetryIcon />} clickable onSelect={onRecenter} />
        )}
      </div>
    </div>
  )
}

/** Quitting is final: a real click, or a deliberately long dwell. */
export const QUIT_DWELL_MS = 2000

export function QuitCorner(): JSX.Element {
  return (
    <CornerTarget id="quit-app" dwellMs={QUIT_DWELL_MS} clickable onSelect={quitApp}
      className="corner-quit" icon={<CloseIcon />} label="Quit" />
  )
}

/** The way into Settings: top-left corner, mirroring STOP, only while idle. */
export function SettingsCorner({ onSelect }: { onSelect: () => void }): JSX.Element {
  return (
    <CornerTarget id="settings-open" dwellMs={SETTINGS_DWELL_MS} clickable onSelect={onSelect}
      className="corner-settings" icon={<GearIcon />} label="Settings" />
  )
}
