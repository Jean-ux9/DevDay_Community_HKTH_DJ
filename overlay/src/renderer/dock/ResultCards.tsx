// How a task ended: a read-only summary, then recovery cards or an OK card (spec §8.4).
import type { CSSProperties, JSX } from 'react'
import { agent, useSession } from '../platform'
import { Card, InfoPanel, PlanCard } from './Card'
import { AlertIcon, CheckIcon, CloseIcon, EyeIcon } from './icons'

export function ResultCards(): JSX.Element | null {
  const s = useSession()
  const result = s.result
  if (!result) return null
  const recovery = s.list?.source === 'recovery' ? s.list : null
  // A failure offers recovery cards; a stop or cancel does not. "Show me the screen" ends
  // ok:true with recovery cards: its summary is what the agent saw.
  const [title, icon, tone] = !result.ok
    ? recovery ? ['That didn’t work', <AlertIcon />, 'is-failed'] : ['Not done', <CloseIcon />, 'is-stopped']
    : recovery ? ['What I see', <EyeIcon />, 'is-look'] : ['Done', <CheckIcon />, 'is-done']
  return (
    <div className="card-row result-row" style={{ '--n': recovery?.items.length || 1 } as CSSProperties}>
      <InfoPanel className={`summary-panel ${tone}`}>
        <span className="info-title">{icon}{title}</span>
        <span className="info-text">{result.summary}</span>
      </InfoPanel>
      {recovery ? recovery.items.map(plan => (
        <PlanCard key={`${recovery.listId}:${plan.id}`} id={`recovery-${recovery.listId}-${plan.id}`} plan={plan}
          disabled={!!s.pendingSelect} onSelect={() => agent.selectPlan(recovery.listId, plan.id)} />
      )) : (
        // Re-sending the current mode is the platform's local reset back to the idle dock.
        <Card id={`result-ok-${result.taskId}`} label="OK" detail="Back to the dock" icon={<CheckIcon />}
          onSelect={() => agent.setMode(s.mode)} />
      )}
    </div>
  )
}
