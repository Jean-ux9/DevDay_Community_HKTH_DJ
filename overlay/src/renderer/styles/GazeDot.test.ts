// @vitest-environment jsdom
import { createElement } from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetPlatform, setGaze } from '../dock/test-platform'
import { CENTER_PULL, GazeDot, MAGNET_PULL } from './GazeDot'

vi.mock('../platform', async () => (await import('../dock/test-platform')).platformMock)

/** A card at (100,100) 200×100, in the given dwell state. */
const card = (state: string) => {
  const el = document.createElement('div')
  el.setAttribute('data-dwell', state)
  el.getBoundingClientRect = () => new DOMRect(100, 100, 200, 100)
  document.body.append(el)
  return el
}
const dot = () => document.querySelector<HTMLElement>('.gaze-dot')!
const at = () => dot().style.transform.match(/translate\(([-\d.]+)px, ([-\d.]+)px\)/)!.slice(1).map(Number)

beforeEach(() => resetPlatform())
afterEach(() => { cleanup(); document.body.innerHTML = '' })

describe('gaze dot', () => {
  it('shows the real point when not in head pointer mode', () => {
    card('active')
    render(createElement(GazeDot))
    act(() => setGaze({ debug: true, point: { x: 120, y: 120 } }))
    expect(at()).toEqual([120, 120])
  })

  it('in head pointer mode it is pulled toward the active card centre', () => {
    card('armed')
    render(createElement(GazeDot))
    act(() => setGaze({ debug: true, headPointer: true, point: { x: 120, y: 120 } }))
    const [x, y] = at()
    expect(x).toBeCloseTo(120 + (200 - 120) * CENTER_PULL)
    expect(y).toBeCloseTo(120 + (150 - 120) * CENTER_PULL)
  })

  it('snaps harder toward the centre when the magnet holds the card from outside', () => {
    card('active')
    render(createElement(GazeDot))
    act(() => setGaze({ source: 'head', point: { x: 380, y: 150 } }))
    const [x, y] = at()
    expect(x).toBeCloseTo(380 + (200 - 380) * MAGNET_PULL)
    expect(y).toBeCloseTo(150)
    expect(dot().className).toContain('is-snapped')
  })

  it('without an active card the dot is not moved', () => {
    card('idle')
    render(createElement(GazeDot))
    act(() => setGaze({ source: 'head', point: { x: 380, y: 150 } }))
    expect(at()).toEqual([380, 150])
  })
})
