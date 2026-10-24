// Screen routing from the session (spec §6.2, §11): confirm > running task > choice > (idle only:
// permissions checklist > calibration > settings) > result > dock.
import { useEffect, useState, type JSX } from 'react'
import { agent, useGaze, useSession } from './platform'
import { AutoDock } from './dock/AutoDock'
import { InfoPanel } from './dock/Card'
import { ChoiceCards } from './dock/ChoiceCards'
import { ModeTabs } from './dock/ModeTabs'
import { ResultCards } from './dock/ResultCards'
import { StatusLine, StatusPill } from './dock/StatusLine'
import { deriveStatus } from './dock/status'
import { ComposerField } from './keyboard/T9Keyboard'
import { TypePanel } from './keyboard/TypePanel'
import { useT9Index } from './keyboard/useT9Index'
import { useTypeFlow } from './keyboard/useTypeFlow'
import { Calibration, type CalibrationTarget } from './screens/Calibration'
import { ConfirmScreen } from './screens/ConfirmScreen'
import { Onboarding } from './screens/Onboarding'
import { QuitCorner, SettingsCorner, SettingsPanel, savedHeadPointer, toggleHeadPointer } from './screens/Settings'
import { missingPermissions } from './screens/permissions'
import { StopTarget } from './stop/StopTarget'
import { GazeDot } from './styles/GazeDot'

type Screen = 'dock' | 'settings' | 'calibration'

export function App(): JSX.Element {
  const s = useSession()
  const gaze = useGaze()
  const flow = useTypeFlow(s)
  const index = useT9Index(s.profile)
  const status = deriveStatus(s, s.mode === 'type' ? flow.awaiting : null)
  const [screen, setScreen] = useState<Screen>('dock')
  const [calibrationTarget, setCalibrationTarget] = useState<CalibrationTarget>('webgazer')
  useEffect(() => { if (savedHeadPointer()) toggleHeadPointer(true) }, [])
  // Eye tracking can't predict anything before training, so it is offered once per launch.
  const [calibrationOffered, setCalibrationOffered] = useState(false)

  const busy = !!s.task || !!s.confirm || !!s.choice || !!s.pendingSelect
  const onboarding = !busy && s.ready && missingPermissions(s, gaze.source).length > 0
  const calibrating = !busy && !onboarding
    && (screen === 'calibration' || (gaze.source === 'webgazer' && !calibrationOffered))
  const closeCalibration = () => { setCalibrationOffered(true); setScreen('dock') }
  // STOP with nothing running: back to the plain main menu (empty Auto dock) from anywhere; clears
  // suggestions and a pending "Thinking…". No new suggestion request: only the Auto tab does that.
  const backToDock = () => {
    closeCalibration()
    flow.backToKeys()
    agent.setMode('auto')
  }

  let body: JSX.Element
  if (s.confirm) {
    body = <ConfirmScreen confirm={s.confirm} />
  } else if (s.task && !s.choice) {
    // While the agent works, the dock collapses so the user can watch (§6.2).
    body = <div className="bottom"><StatusPill task={s.task} status={status} /></div>
  } else if (onboarding) {
    body = <Onboarding />
  } else if (calibrating) {
    body = <Calibration key={calibrationTarget} target={calibrationTarget} onDone={closeCalibration} onCancel={closeCalibration} />
  } else {
    let content: JSX.Element
    let tabs = true
    if (s.choice) { content = <ChoiceCards choice={s.choice} />; tabs = false }
    else if (!s.ready) content = (
      <InfoPanel className="connection-panel">
        <span className="info-title">{status.text}</span>
        <span className="info-text">{status.kind === 'error'
          ? 'Check that the agent is running, then restart the overlay.'
          : 'The cards appear as soon as the agent answers.'}</span>
      </InfoPanel>
    )
    else if (screen === 'settings') {
      content = <SettingsPanel onRecalibrate={target => { setCalibrationTarget(target); setScreen('calibration') }}
        onClose={() => setScreen('dock')} />
      tabs = false
    }
    else if (s.result) content = <ResultCards />
    else if (s.mode === 'auto') content = <AutoDock />
    else content = <TypePanel flow={flow} index={index} />
    const typing = tabs && s.ready && !s.result && s.mode === 'type' && flow.view === 'keys'
    body = (
      <>
        {!busy && s.ready && screen === 'dock' && <SettingsCorner onSelect={() => setScreen('settings')} />}
        {!busy && <QuitCorner />}
        <div className="bottom">
          <div className="above-dock">
            <StatusLine status={status} />
            {gaze.clickMode && <span className="mode-chip">Click mode · ⌃⌥⌘D</span>}
            {typing && <ComposerField composer={flow.composer} index={index} />}
          </div>
          <section className={`dock${typing ? ' dock-typing' : ''}`}>
            {tabs && <ModeTabs mode={s.mode} disabled={!s.ready || !!s.pendingSelect} />}
            <div className="dock-content">{content}</div>
          </section>
        </div>
      </>
    )
  }

  return (
    <div className={`overlay density-${s.settings?.density ?? 'large'}${gaze.headPointer || gaze.source === 'head' ? ' head-pointer' : ''}`}>
      {body}
      {/* Not during calibration: it sits on the dots' corner and distracts. No task can run then. */}
      {!calibrating && <StopTarget onIdle={backToDock} />}
      <GazeDot />
    </div>
  )
}
