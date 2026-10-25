// Auto mode: "Suggest now", then 3–4 suggestions, then "Something else → Type" (spec §6.2, §7).
import type { CSSProperties, JSX } from 'react'
import { DwellTarget, agent, useSession } from '../platform'
import { Card, PlanCard } from './Card'
import { KeyboardIcon, SparkleIcon, Spinner } from './icons'
import { switchMode } from './ModeTabs'

export function AutoDock(): JSX.Element {
  const s = useSession()
  const list = s.list?.source === 'suggestions' ? s.list : null
  const items = list ? list.items.filter(p => p.kind !== 'other').slice(0, 4) : []
  const pending = s.suggestPending
  return (
    // One row: "Suggest now" | suggestions | "Something else" (pinned to the last column).
    <div className="card-row auto-row" data-n={Math.max(1, items.length)}
      style={{ '--n': Math.max(1, items.length) } as CSSProperties}>
      {/* Dwelling this is the only way Auto calls the model by default (spec §1, §7). */}
      <DwellTarget id="suggest-now" variant="card" disabled={!s.ready || pending || !!s.pendingSelect}
        onSelect={() => agent.suggestNow()}
        className={`target card suggest-card${pending ? ' is-pending' : ''}${!list && !pending ? ' is-inviting' : ''}`}>
        <span className="card-icon">{pending ? <Spinner /> : <SparkleIcon />}</span>
        <span className="card-label">{pending ? 'Thinking…' : 'Suggest now'}</span>
        <span className="card-detail">
          {pending ? 'Reading your screen' : list ? `New ideas for ${list.app}` : 'Ideas for this screen'}
        </span>
      </DwellTarget>
      {list && items.map(plan => (
        <PlanCard key={`${list.listId}:${plan.id}`} id={`suggestion-${list.listId}-${plan.id}`} plan={plan}
          disabled={!!s.pendingSelect} onSelect={() => agent.selectPlan(list.listId, plan.id)} />
      ))}
      <Card id="auto-other" label="Something else" detail="Type what you want" icon={<KeyboardIcon />}
        className="other-card" disabled={!!s.pendingSelect} onSelect={() => switchMode(s.mode, 'type')} />
    </div>
  )
}
