// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DwellTarget } from './DwellTarget'
import { DwellContext, DwellStore } from './context'
let store: DwellStore
beforeEach(() => {
  store = new DwellStore()
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(100, 100, 160, 120))
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })
const mount = (select = vi.fn(), variant: 'card' | 'confirm' | 'stop' = 'card') => {
  const view = render(createElement(DwellContext.Provider, { value: store },
    createElement(DwellTarget, { id: 'target', variant, onSelect: select, children: 'Target' })))
  return { ...view, node: view.getByText('Target'), select }
}
const feed = (from: number, to: number) => act(() => {
  for (let t = from; t <= to; t += 10) { store.measure(); store.manager.update({ x: 180, y: 160, t }); store.publish() }
})
describe('DwellTarget DOM contract with a fake gaze clock', () => {
  it('registers, exposes active/armed/progress, selects once, and unregisters', () => {
    const { node, select, unmount } = mount()
    expect(node.getAttribute('data-dwell')).toBe('idle')
    feed(0, 120)
    expect(node.getAttribute('data-dwell')).toBe('active')
    expect(Number(node.style.getPropertyValue('--dwell-progress'))).toBeGreaterThan(0)
    feed(130, 350)
    expect(node.getAttribute('data-dwell')).toBe('armed')
    feed(360, 1000)
    expect(select).toHaveBeenCalledTimes(1)
    expect(node.getAttribute('data-dwell')).toBe('selected')
    feed(1010, 1300)
    expect(select).toHaveBeenCalledTimes(1)
    unmount()
    feed(2000, 4000)
    expect(select).toHaveBeenCalledTimes(1)
    expect(store.manager.getState().activeId).toBeNull()
  })
  it('uses current settings without re-registering and calls the latest callback', () => {
    const first = vi.fn(), second = vi.fn()
    const { rerender } = mount(first)
    store.options.dwellMs = 1200
    rerender(createElement(DwellContext.Provider, { value: store }, createElement(DwellTarget,
      { id: 'target', variant: 'card', onSelect: second, children: 'Target' })))
    feed(0, 1100)
    expect(second).not.toHaveBeenCalled()
    feed(1110, 1400)
    expect(second).toHaveBeenCalledTimes(1)
    expect(first).not.toHaveBeenCalled()
  })
  it('uses the longer confirm duration and the fixed STOP duration', () => {
    const confirm = mount(vi.fn(), 'confirm')
    feed(0, 1200)
    expect(confirm.select).not.toHaveBeenCalled()
    feed(1210, 1700)
    expect(confirm.select).toHaveBeenCalledTimes(1)
    confirm.unmount()
    store = new DwellStore()
    const stop = mount(vi.fn(), 'stop')
    feed(0, 520)
    expect(stop.select).toHaveBeenCalledTimes(1)
  })
  it('never registers a selectable hidden or disabled target', () => {
    const { node, select } = mount()
    node.hidden = true
    feed(0, 1500)
    expect(select).not.toHaveBeenCalled()
  })
})
