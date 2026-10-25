// Corner controls (Back, Hide, Settings, Quit): at rest a small circle with only the icon. Gazed at,
// it zooms to the full square and shows its label; the dwell trace starts once the zoom is done.
import type { JSX, ReactNode } from 'react'
import { DwellTarget, type DwellTargetProps } from '../platform'

/** The zoom from circle to square (styles/glass.css .corner); dwell progress waits for it. */
export const CORNER_ZOOM_MS = 300

type CornerProps = Omit<DwellTargetProps, 'children' | 'variant'> & {
  variant?: DwellTargetProps['variant']
  icon: ReactNode
  label: string
  sub?: string
}

export function CornerTarget({ icon, label, sub, className, variant = 'card', ...props }: CornerProps): JSX.Element {
  return (
    <DwellTarget variant={variant} startDelayMs={CORNER_ZOOM_MS} {...props}
      className={['target', 'corner', className].filter(Boolean).join(' ')}>
      <span className="corner-icon">{icon}</span>
      <span className="corner-text">
        <span className="corner-label">{label}</span>
        {sub && <span className="corner-sub">{sub}</span>}
      </span>
    </DwellTarget>
  )
}
