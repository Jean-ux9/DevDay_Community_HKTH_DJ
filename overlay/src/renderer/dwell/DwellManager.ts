// The one global hit-tester behind every <DwellTarget> (spec §5.2). Pure logic: it is fed filtered
// gaze samples with their own timestamps, so it is deterministic and unit-testable without a DOM.

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export type DwellVariant = 'key' | 'card' | 'confirm' | 'stop'

export interface SelectEvent {
  id: string
  /** Target centre in screen px: the passive-recalibration training point for WebGazer. */
  center: { x: number; y: number }
  t: number
}

export interface DwellTargetSpec {
  id: string
  rect: Rect
  dwellMs: number
  /** Extra px around `rect` that still count as "under the gaze". */
  hitPadding?: number
  variant: DwellVariant
  disabled?: boolean
  onSelect?: (e: SelectEvent) => void
}

export interface GazePoint {
  x: number
  y: number
  /** ms; any monotonic clock. */
  t: number
}

export interface DwellState {
  activeId: string | null
  armed: boolean
  progress: Readonly<Record<string, number>>
  locked: boolean
  lastSelect: SelectEvent | null
}

export const DEFAULT_HIT_PADDING = 24
/** The active target stays active while the gaze is within its rect + this margin ... */
export const STICKY_MARGIN_PX = 40
/** ... until the gaze has been outside that zone for this long. */
export const STICKY_RELEASE_MS = 150
/** A new target must be under the gaze this long before it becomes active. */
export const ENTRY_DELAY_MS = 100
/**
 * Moving from an active target onto a neighbouring key needs longer than entering from nothing,
 * so a gaze drifting across a tightly packed keyboard doesn't keep switching keys.
 */
export const KEY_SWITCH_DELAY_MS = 200
/** Progress decays this many times faster than it fills when the gaze leaves. */
export const DECAY_FACTOR = 2
/** After any select, every target except STOP is locked for this long. */
export const COOLDOWN_MS = 600
/** Blink select needs the target to have been active this long ("armed"). */
export const BLINK_ARM_MS = 200
export const STOP_DWELL_MS = 400
/** A long gap between samples (tab stall, gaze lost) must not complete a dwell by itself. */
const MAX_STEP_MS = 250

/** CONFIRM uses a longer dwell than the user's normal setting (spec §5.2). */
export const confirmDwellMs = (dwellMs: number): number => Math.max(1500, dwellMs * 1.5)

const contains = (r: Rect, x: number, y: number, pad: number): boolean =>
  x >= r.x - pad && x <= r.x + r.w + pad && y >= r.y - pad && y <= r.y + r.h + pad

const centerOf = (r: Rect) => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 })

const isExempt = (s: DwellTargetSpec): boolean => s.variant === 'stop'

export class DwellManager {
  private readonly targets = new Map<string, DwellTargetSpec>()
  private readonly progress = new Map<string, number>()
  private readonly listeners = new Set<(e: SelectEvent) => void>()

  private activeId: string | null = null
  private activeSince = 0
  private outsideSince: number | null = null
  private candidateId: string | null = null
  private candidateSince = 0
  private lockedUntil = -Infinity
  private lastT: number | null = null
  private paused = false
  private lastSelect: SelectEvent | null = null

  /** Registers (or replaces) a target. Returns an unregister function. */
  register(spec: DwellTargetSpec): () => void {
    this.targets.set(spec.id, spec)
    return () => this.unregister(spec.id)
  }

  unregister(id: string): void {
    this.targets.delete(id)
    this.progress.delete(id)
    if (this.activeId === id) this.deactivate()
    if (this.candidateId === id) this.candidateId = null
  }

  /** Called for every completed select (used for WebGazer passive recalibration). */
  onSelect(listener: (e: SelectEvent) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  /** A blink in progress pauses dwell progress so a normal blink doesn't break it. */
  setPaused(paused: boolean): void {
    this.paused = paused
  }

  /** Camera loss, source switches, hidden overlay and reconnects cannot retain a partial dwell. */
  loseGaze(): void {
    this.deactivate()
    this.candidateId = null
    this.progress.clear()
    this.lastT = null
  }

  update(sample: GazePoint): void {
    const { x, y, t } = sample
    if (![x, y, t].every(Number.isFinite)) return
    if (this.lastT !== null && t - this.lastT > MAX_STEP_MS) this.loseGaze()
    const dt = this.lastT === null ? 0 : Math.min(Math.max(t - this.lastT, 0), MAX_STEP_MS)
    this.lastT = t
    const locked = t < this.lockedUntil

    this.checkActive(x, y, t, locked)
    this.checkCandidate(x, y, t, locked)
    this.advanceProgress(dt)

    const active = this.activeId === null ? undefined : this.targets.get(this.activeId)
    if (active && (this.progress.get(active.id) ?? 0) >= 1) this.select(active, t)
  }

  /** Blink select: fires only for a target that has been active ("armed") for ≥200 ms. */
  blinkSelect(t: number): boolean {
    const active = this.activeId === null ? undefined : this.targets.get(this.activeId)
    if (!active || active.disabled || t - this.activeSince < BLINK_ARM_MS) return false
    if (t < this.lockedUntil && !isExempt(active)) return false
    this.select(active, t)
    return true
  }

  getState(): DwellState {
    return {
      activeId: this.activeId,
      armed: this.activeId !== null && this.lastT !== null && this.lastT - this.activeSince >= BLINK_ARM_MS,
      progress: Object.fromEntries(this.progress),
      locked: this.lastT !== null && this.lastT < this.lockedUntil,
      lastSelect: this.lastSelect
    }
  }

  progressOf(id: string): number {
    return this.progress.get(id) ?? 0
  }

  private eligible(s: DwellTargetSpec, locked: boolean): boolean {
    return !s.disabled && (!locked || isExempt(s))
  }

  private checkActive(x: number, y: number, t: number, locked: boolean): void {
    const active = this.activeId === null ? undefined : this.targets.get(this.activeId)
    if (!active || !this.eligible(active, locked)) {
      this.deactivate()
      return
    }
    if (contains(active.rect, x, y, STICKY_MARGIN_PX)) {
      this.outsideSince = null
    } else {
      this.outsideSince ??= t
      if (t - this.outsideSince >= STICKY_RELEASE_MS) this.deactivate()
    }
  }

  private checkCandidate(x: number, y: number, t: number, locked: boolean): void {
    const hit = this.hitTest(x, y, locked)
    if (!hit || hit.id === this.activeId) {
      this.candidateId = null
      return
    }
    const active = this.activeId === null ? undefined : this.targets.get(this.activeId)
    // While the gaze is still on the active target's own hit area, it keeps the claim.
    if (active && contains(active.rect, x, y, active.hitPadding ?? DEFAULT_HIT_PADDING)) {
      this.candidateId = null
      return
    }
    if (this.candidateId !== hit.id) {
      this.candidateId = hit.id
      this.candidateSince = t
    }
    const delay = active && hit.variant === 'key' ? KEY_SWITCH_DELAY_MS : ENTRY_DELAY_MS
    if (t - this.candidateSince >= delay) {
      this.activate(hit.id, t)
    }
  }

  /** Nearest eligible target (by centre) whose padded rect contains the point. */
  private hitTest(x: number, y: number, locked: boolean): DwellTargetSpec | null {
    let best: DwellTargetSpec | null = null
    let bestDist = Infinity
    for (const s of this.targets.values()) {
      if (!this.eligible(s, locked)) continue
      if (!contains(s.rect, x, y, s.hitPadding ?? DEFAULT_HIT_PADDING)) continue
      const c = centerOf(s.rect)
      const d = (c.x - x) ** 2 + (c.y - y) ** 2
      if (d < bestDist) {
        best = s
        bestDist = d
      }
    }
    return best
  }

  private activate(id: string, t: number): void {
    this.activeId = id
    this.activeSince = t
    this.outsideSince = null
    this.candidateId = null
  }

  private deactivate(): void {
    this.activeId = null
    this.outsideSince = null
  }

  private advanceProgress(dt: number): void {
    if (this.paused || dt === 0) return
    for (const id of [...this.progress.keys()]) {
      if (id === this.activeId && this.outsideSince === null) continue // filled below
      const s = this.targets.get(id)
      const p = (this.progress.get(id) ?? 0) - (DECAY_FACTOR * dt) / (s?.dwellMs ?? 1)
      if (p <= 0) this.progress.delete(id)
      else this.progress.set(id, p)
    }
    const active = this.activeId === null ? undefined : this.targets.get(this.activeId)
    if (active && this.outsideSince === null) {
      this.progress.set(active.id, Math.min(1, (this.progress.get(active.id) ?? 0) + dt / active.dwellMs))
    }
  }

  private select(spec: DwellTargetSpec, t: number): void {
    const event: SelectEvent = { id: spec.id, center: centerOf(spec.rect), t }
    this.lastSelect = event
    this.lockedUntil = t + COOLDOWN_MS
    this.candidateId = null
    this.deactivate()
    for (const id of [...this.progress.keys()]) {
      const s = this.targets.get(id)
      if (!s || !isExempt(s) || id === spec.id) this.progress.delete(id)
    }
    spec.onSelect?.(event)
    for (const l of this.listeners) l(event)
  }
}
