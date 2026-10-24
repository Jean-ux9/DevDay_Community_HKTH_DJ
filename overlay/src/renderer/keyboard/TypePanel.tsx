// Type mode: keyboard, then the decoded sentence cards, then the plan cards (spec §6.2–6.3).
import type { JSX } from 'react'
import { agent, useSession } from '../platform'
import { Card, InfoPanel, PlanCard } from '../dock/Card'
import { AlertIcon, ArrowLeftIcon, Spinner } from '../dock/icons'
import { T9Keyboard } from './T9Keyboard'
import type { T9Index } from './t9index'
import type { TypeFlow } from './useTypeFlow'

function Waiting({ text }: { text: string }): JSX.Element {
  return <InfoPanel className="waiting-panel"><span className="info-title"><Spinner />{text}</span></InfoPanel>
}

function Failure({ text }: { text: string }): JSX.Element {
  return (
    <InfoPanel className="summary-panel is-failed">
      <span className="info-title"><AlertIcon />That didn’t work</span>
      <span className="info-text">{text}</span>
    </InfoPanel>
  )
}

export function TypePanel({ flow, index }: { flow: TypeFlow; index: T9Index }): JSX.Element {
  const s = useSession()
  const back = <Card id={`type-back-${flow.view}`} label="Back to keyboard" detail="Your text is kept"
    icon={<ArrowLeftIcon />} className="back-card" onSelect={flow.backToKeys} />

  if (flow.view === 'sentences') {
    return (
      <div className="dock-section">
        <h2 className="dock-question">Which did you mean?</h2>
        <div className="card-row">
          {flow.sentences.map((text, i) => (
            <Card key={`${i}:${text}`} id={`sentence-${i}-${text}`} label={text} className="sentence-card"
              onSelect={() => flow.chooseSentence(text)} />
          ))}
          {flow.awaiting === 'decode' && <Waiting text="Finding the best wording…" />}
          {flow.failure && <Failure text={flow.failure} />}
          {back}
        </div>
      </div>
    )
  }

  if (flow.view === 'plans') {
    const list = flow.plans
    return (
      <div className="dock-section">
        <h2 className="dock-question">
          What should I do?{flow.intent && <span className="dock-quote"> You asked: “{flow.intent}”</span>}
        </h2>
        <div className="card-row">
          {list?.items.map(plan => (
            <PlanCard key={`${list.listId}:${plan.id}`} id={`plan-${list.listId}-${plan.id}`} plan={plan}
              disabled={!!s.pendingSelect}
              onSelect={() => {
                // "other" is handled locally by the platform: it returns here with the text kept.
                if (agent.selectPlan(list.listId, plan.id) && plan.id === 'other') flow.backToKeys()
              }} />
          ))}
          {flow.awaiting === 'plans' && <Waiting text="Working out what to do…" />}
          {flow.failure && <Failure text={flow.failure} />}
          {!list && back}
        </div>
      </div>
    )
  }

  return <T9Keyboard composer={flow.composer} index={index} onChange={flow.setComposer} onDone={flow.done} />
}
