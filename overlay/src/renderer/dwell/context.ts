import { createContext, useContext } from 'react'
import { DwellManager, type DwellState, type DwellTargetSpec } from './DwellManager'
export interface DwellOptions { dwellMs: number; connected: boolean }
/** One shared manager for the whole overlay; tests may inject an isolated store via context. */
export class DwellStore {
  readonly manager = new DwellManager()
  private snapshot: DwellState = this.manager.getState()
  private readonly listeners = new Set<() => void>()
  private readonly measures = new Map<string, () => void>()
  options: DwellOptions = { dwellMs: 800, connected: false }
  constructor() { this.manager.onSelect(() => this.publish()) }
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  getSnapshot = (): DwellState => this.snapshot
  publish(): void { this.snapshot = this.manager.getState(); for (const listener of this.listeners) listener() }
  register(spec: DwellTargetSpec, measure: () => void): () => void {
    const unregister = this.manager.register(spec)
    this.measures.set(spec.id, measure)
    return () => { unregister(); this.measures.delete(spec.id); this.publish() }
  }
  measure(): void { for (const measure of this.measures.values()) measure() }
}
export const dwellStore = new DwellStore()
export const DwellContext = createContext(dwellStore)
export const useDwellStore = (): DwellStore => useContext(DwellContext)
