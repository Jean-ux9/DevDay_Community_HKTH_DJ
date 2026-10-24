// Screen routing from the session (spec §6.2): confirm > running task > choice > result > dock.
import type { JSX } from 'react'
import { useSession } from './platform'
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
import { ConfirmScreen } from './screens/ConfirmScreen'
import { StopTarget } from './stop/StopTarget'
import { GazeDot } from './styles/GazeDot'

export function App(): JSX.Element {
  const s = useSession()
  const flow = useTypeFlow(s)
  const index = useT9Index(s.profile)
  const status = deriveStatus(s, s.mode === 'type' ? flow.awaiting : null)

  let body: JSX.Element
  if (s.confirm) {
    body = <ConfirmScreen confirm={s.confirm} />
  } else if (s.task && !s.choice) {
    // While the agent works, the dock collapses so the user can watch (§6.2).
    body = <div className="bottom"><StatusPill task={s.task} status={status} /></div>
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
    else if (s.result) content = <ResultCards />
    else if (s.mode === 'auto') content = <AutoDock />
    else content = <TypePanel flow={flow} index={index} />
    const typing = s.ready && !s.choice && !s.result && s.mode === 'type' && flow.view === 'keys'
    body = (
      <div className="bottom">
        <div className="above-dock">
          <StatusLine status={status} />
          {typing && <ComposerField composer={flow.composer} index={index} />}
        </div>
        <section className={`dock${typing ? ' dock-typing' : ''}`}>
          {tabs && <ModeTabs mode={s.mode} disabled={!s.ready || !!s.pendingSelect} />}
          <div className="dock-content">{content}</div>
        </section>
      </div>
    )
  }

  return (
    <div className={`overlay density-${s.settings?.density ?? 'large'}`}>
      {body}
      <StopTarget />
      <GazeDot />
    </div>
  )
}
