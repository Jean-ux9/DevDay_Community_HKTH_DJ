import { useLayoutEffect, useRef, useSyncExternalStore, type CSSProperties, type JSX, type ReactNode } from 'react'
import { confirmDwellMs, type DwellVariant, type DwellTargetSpec } from './DwellManager'
import { useDwellStore } from './context'
export interface DwellTargetProps {
  id: string
  variant: DwellVariant
  dwellMs?: number
  hitPadding?: number
  disabled?: boolean
  /** Also selects on a real mouse click (caregiver controls). In click mode every target does. */
  clickable?: boolean
  onSelect: () => void
  className?: string
  children: ReactNode
}
/** No visuals or pointer-based selection: A1 draws the CSS ring from the exposed state. */
export function DwellTarget(props: DwellTargetProps): JSX.Element {
  const store = useDwellStore()
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot)
  const element = useRef<HTMLDivElement>(null)
  const current = useRef(props)
  current.current = props
  useLayoutEffect(() => {
    const spec: DwellTargetSpec = { id: props.id, variant: props.variant, dwellMs: 1300,
      rect: { x: 0, y: 0, w: 0, h: 0 }, onSelect: () => current.current.onSelect() }
    const measure = () => {
      const node = element.current, p = current.current
      if (!node) return
      const rect = node.getBoundingClientRect()
      spec.rect = { x: rect.x, y: rect.y, w: rect.width, h: rect.height }
      const normal = p.dwellMs ?? store.options.dwellMs
      spec.dwellMs = p.variant === 'stop' ? 400 : p.variant === 'confirm' ? confirmDwellMs(normal) : normal
      spec.hitPadding = p.hitPadding ?? 24
      spec.disabled = !!p.disabled || rect.width === 0 || rect.height === 0 || !!node.hidden || getComputedStyle(node).visibility === 'hidden'
    }
    measure()
    return store.register(spec, measure)
  }, [props.id, props.variant, store])
  const progress = state.progress[props.id] ?? 0
  const status = state.lastSelect?.id === props.id && state.locked ? 'selected'
    : state.locked && props.variant !== 'stop' ? 'cooldown'
    : state.activeId === props.id ? state.armed ? 'armed' : 'active' : 'idle'
  // data-caregiver-clickable makes the window take the click while idle (platform README).
  const clickable = !!props.clickable || store.options.clickMode
  return <div ref={element} className={props.className} data-dwell-id={props.id} data-dwell={status}
    data-caregiver-clickable={clickable ? '' : undefined}
    onClick={clickable ? () => { if (!current.current.disabled) current.current.onSelect() } : undefined}
    aria-disabled={props.disabled || undefined} style={{ '--dwell-progress': progress } as CSSProperties}>{props.children}</div>
}
