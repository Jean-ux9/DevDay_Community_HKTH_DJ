// Small line icons. Always shown next to a text label, never alone.
import type { JSX, ReactNode } from 'react'

const Icon = ({ children }: { children: ReactNode }): JSX.Element => (
  <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
)

export const SparkleIcon = (): JSX.Element => (
  <Icon><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" /></Icon>
)
export const KeyboardIcon = (): JSX.Element => (
  <Icon><rect x="2" y="6" width="20" height="13" rx="2" /><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 15h10" /></Icon>
)
export const ArrowRightIcon = (): JSX.Element => <Icon><path d="M5 12h14M13 6l6 6-6 6" /></Icon>
export const ArrowLeftIcon = (): JSX.Element => <Icon><path d="M19 12H5M11 6l-6 6 6 6" /></Icon>
export const CheckIcon = (): JSX.Element => <Icon><path d="M4 12.5l5 5L20 6.5" /></Icon>
export const AlertIcon = (): JSX.Element => (
  <Icon><path d="M12 3l10 18H2z" /><path d="M12 10v5M12 18h.01" /></Icon>
)
export const RetryIcon = (): JSX.Element => <Icon><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></Icon>
export const EyeIcon = (): JSX.Element => (
  <Icon><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></Icon>
)
export const CloseIcon = (): JSX.Element => <Icon><path d="M6 6l12 12M18 6L6 18" /></Icon>
export const ShieldIcon = (): JSX.Element => (
  <Icon><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M9 12l2 2 4-4" /></Icon>
)
export const DeleteIcon = (): JSX.Element => (
  <Icon><path d="M21 5H8l-6 7 6 7h13z" /><path d="M17 9l-6 6M11 9l6 6" /></Icon>
)
export const SpaceIcon = (): JSX.Element => <Icon><path d="M3 10v4h18v-4" /></Icon>

/** Busy indicator; its text label sits next to it. */
export const Spinner = (): JSX.Element => <span className="spinner" role="progressbar" aria-label="Working" />
