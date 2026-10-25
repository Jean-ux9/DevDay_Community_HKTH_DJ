import { describe, expect, it, vi } from 'vitest'
import {
  BLINK_ARM_MS,
  COOLDOWN_MS,
  DwellManager,
  KEY_SWITCH_DELAY_MS,
  type DwellTargetSpec,
  confirmDwellMs
} from './DwellManager'

const FRAME_MS = 1000 / 60

const target = (id: string, x: number, y: number, over: Partial<DwellTargetSpec> = {}): DwellTargetSpec => ({
  id,
  rect: { x, y, w: 160, h: 120 },
  dwellMs: 800,
  variant: 'card',
  ...over
})

/** Feeds `ms` of samples at 60 Hz, starting at `clock.t`, from `at(t0)`; returns nothing. */
const makeRig = (m: DwellManager) => {
  const clock = { t: 0 }
  const feed = (ms: number, at: (elapsed: number) => { x: number; y: number }) => {
    const start = clock.t
    for (let e = 0; e <= ms + 1e-6; e += FRAME_MS) {
      const p = at(e)
      m.update({ x: p.x, y: p.y, t: start + e })
    }
    clock.t = start + ms + FRAME_MS
  }
  const hold = (ms: number, x: number, y: number) => feed(ms, () => ({ x, y }))
  return { clock, feed, hold }
}

// Deterministic noise in [-1, 1].
const rng = (seed: number) => () => {
  seed = (seed * 1664525 + 1013904223) % 4294967296
  return (seed / 4294967296) * 2 - 1
}

describe('DwellManager: entry and selection', () => {
  it('selects after the entry delay plus dwellMs', () => {
    const m = new DwellManager()
    const onSelect = vi.fn()
    m.register(target('a', 400, 400, { onSelect }))
    const { clock, hold } = makeRig(m)
    hold(850, 480, 460)
    expect(onSelect).not.toHaveBeenCalled()
    hold(300, 480, 460)
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0]![0].id).toBe('a')
    expect(clock.t).toBeGreaterThan(0)
  })

  it('does not activate a target the gaze only crosses for <100 ms', () => {
    const m = new DwellManager()
    m.register(target('a', 400, 400))
    const { hold } = makeRig(m)
    hold(80, 480, 460)
    expect(m.getState().activeId).toBeNull()
    hold(400, 1500, 900)
    expect(m.progressOf('a')).toBe(0)
  })

  it('becomes active once the gaze has been there ≥100 ms', () => {
    const m = new DwellManager()
    m.register(target('a', 400, 400))
    const { hold } = makeRig(m)
    hold(150, 480, 460)
    expect(m.getState().activeId).toBe('a')
  })

  it('reports the target centre and notifies global listeners', () => {
    const m = new DwellManager()
    const heard = vi.fn()
    m.onSelect(heard)
    m.register(target('a', 400, 400))
    const { hold } = makeRig(m)
    hold(1200, 480, 460)
    expect(heard).toHaveBeenCalledWith(expect.objectContaining({ id: 'a', center: { x: 480, y: 460 } }))
  })

  it('never activates a disabled target', () => {
    const m = new DwellManager()
    m.register(target('a', 400, 400, { disabled: true }))
    const { hold } = makeRig(m)
    hold(2000, 480, 460)
    expect(m.getState().activeId).toBeNull()
  })

  it('hit padding extends the target', () => {
    const m = new DwellManager()
    m.register(target('a', 400, 400)) // padding 24 by default
    const { hold } = makeRig(m)
    hold(200, 390, 460) // 10 px left of the rect
    expect(m.getState().activeId).toBe('a')
  })

  it('unregister drops the target and its progress', () => {
    const m = new DwellManager()
    const off = m.register(target('a', 400, 400))
    const { hold } = makeRig(m)
    hold(400, 480, 460)
    expect(m.progressOf('a')).toBeGreaterThan(0)
    off()
    expect(m.progressOf('a')).toBe(0)
    expect(m.getState().activeId).toBeNull()
  })
})

describe('DwellManager: sticky target', () => {
  it('stays active while the gaze is within rect + 40 px, however long', () => {
    const m = new DwellManager()
    m.register(target('a', 400, 400, { dwellMs: 60_000 }))
    const { hold } = makeRig(m)
    hold(200, 480, 460)
    hold(3000, 400 + 160 + 35, 460) // 35 px right of the rect edge
    expect(m.getState().activeId).toBe('a')
  })

  it('releases only after ≥150 ms outside rect + 40 px', () => {
    const m = new DwellManager()
    m.register(target('a', 400, 400, { dwellMs: 60_000 }))
    const { hold } = makeRig(m)
    hold(200, 480, 460)
    hold(100, 900, 460) // well outside, but only briefly
    expect(m.getState().activeId).toBe('a')
    hold(100, 480, 460) // back: the outside timer resets
    hold(100, 900, 460)
    expect(m.getState().activeId).toBe('a')
    hold(200, 900, 460)
    expect(m.getState().activeId).toBeNull()
  })

  it('a neighbour takes over after 100 ms when the gaze leaves the active hit area', () => {
    const m = new DwellManager()
    m.register(target('a', 400, 400, { dwellMs: 60_000 }))
    m.register(target('b', 600, 400, { dwellMs: 60_000 })) // 40 px gap
    const { hold } = makeRig(m)
    hold(200, 480, 460)
    expect(m.getState().activeId).toBe('a')
    hold(60, 680, 460)
    expect(m.getState().activeId).toBe('a')
    hold(100, 680, 460)
    expect(m.getState().activeId).toBe('b')
  })
})

describe('DwellManager: switching between keys', () => {
  const keys = () => {
    const m = new DwellManager()
    m.register(target('k1', 400, 400, { variant: 'key', dwellMs: 60_000 }))
    m.register(target('k2', 600, 400, { variant: 'key', dwellMs: 60_000 })) // 40 px gap
    return m
  }

  it('a neighbouring key takes over only after 200 ms', () => {
    const m = keys()
    const { hold } = makeRig(m)
    hold(200, 480, 460)
    expect(m.getState().activeId).toBe('k1')
    hold(150, 680, 460) // 100 ms is not enough for a key
    expect(m.getState().activeId).toBe('k1')
    hold(KEY_SWITCH_DELAY_MS, 680, 460)
    expect(m.getState().activeId).toBe('k2')
  })

  it('the first key entered from nothing still needs only 100 ms', () => {
    const m = keys()
    const { hold } = makeRig(m)
    hold(150, 480, 460)
    expect(m.getState().activeId).toBe('k1')
  })
})

describe('DwellManager: decay', () => {
  it('progress decays at 2× speed instead of resetting', () => {
    const m = new DwellManager()
    m.register(target('a', 400, 400))
    const { hold } = makeRig(m)
    hold(100 + 400, 480, 460) // entry + half of the dwell
    const before = m.progressOf('a')
    expect(before).toBeGreaterThan(0.4)
    expect(before).toBeLessThan(0.6)
    hold(100, 1500, 900) // looks away for 100 ms (still inside the 150 ms release window)
    const after = m.progressOf('a')
    // 100 ms away at 2× = 0.25 of an 800 ms dwell
    expect(before - after).toBeGreaterThan(0.2)
    expect(before - after).toBeLessThan(0.3)
    expect(after).toBeGreaterThan(0)
  })

  it('a tremor excursion does not lose the dwell', () => {
    const m = new DwellManager()
    const onSelect = vi.fn()
    m.register(target('a', 400, 400, { onSelect }))
    const { hold } = makeRig(m)
    hold(300, 480, 460)
    hold(100, 900, 460) // glance away
    hold(900, 480, 460)
    expect(onSelect).toHaveBeenCalledTimes(1)
  })
})

describe('DwellManager: cooldown', () => {
  const setup = () => {
    const m = new DwellManager()
    const onA = vi.fn()
    const onB = vi.fn()
    const onStop = vi.fn()
    m.register(target('a', 100, 100, { onSelect: onA }))
    m.register(target('b', 500, 100, { onSelect: onB }))
    m.register({ id: 'stop', rect: { x: 1000, y: 0, w: 160, h: 160 }, dwellMs: 400, variant: 'stop', onSelect: onStop })
    return { m, onA, onB, onStop }
  }

  it('locks every other target for 600 ms after a select', () => {
    const { m, onA, onB } = setup()
    const { clock, hold } = makeRig(m)
    hold(1200, 180, 160)
    expect(onA).toHaveBeenCalledTimes(1)
    const selectedAt = m.getState().lastSelect!.t
    // Look straight at b right after the select: it must not even become active during the lock.
    clock.t = selectedAt + FRAME_MS
    hold(COOLDOWN_MS - 2 * FRAME_MS, 580, 160)
    expect(m.getState().activeId).toBeNull()
    expect(onB).not.toHaveBeenCalled()
    // After the lock it still needs entry delay + a full dwell.
    hold(150, 580, 160)
    expect(m.getState().activeId).toBe('b')
    hold(1000, 580, 160)
    expect(onB).toHaveBeenCalledTimes(1)
  })

  it('does not select the same target twice during the cooldown', () => {
    const { m, onA } = setup()
    const { hold } = makeRig(m)
    hold(5000, 180, 160)
    // 5 s on one target: one select, then re-entry (600 ms lock + 100 ms entry + 800 ms) → ≥ 1 more only after ~1.5 s
    expect(onA.mock.calls.length).toBeLessThanOrEqual(3)
    expect(onA.mock.calls.length).toBeGreaterThanOrEqual(2)
    const times = onA.mock.calls.map((c) => c[0].t as number)
    for (let i = 1; i < times.length; i++) {
      expect(times[i]! - times[i - 1]!).toBeGreaterThanOrEqual(COOLDOWN_MS)
    }
  })

  it('STOP is exempt: it can be selected inside another target’s cooldown', () => {
    const { m, onA, onStop } = setup()
    const { clock, hold } = makeRig(m)
    hold(1200, 180, 160)
    expect(onA).toHaveBeenCalledTimes(1)
    const selectedAt = m.getState().lastSelect!.t
    clock.t = selectedAt + FRAME_MS
    hold(450 + 150, 1080, 80) // entry delay + STOP's 400 ms dwell, all inside the 600 ms lock window
    expect(m.getState().lastSelect!.id).toBe('stop')
    expect(onStop).toHaveBeenCalledTimes(1)
  })
})

describe('DwellManager: tremor', () => {
  it('a ±30 px tremor stream still selects within dwellMs + 300 ms', () => {
    for (const seed of [1, 2, 3, 4, 5]) {
      const m = new DwellManager()
      const onSelect = vi.fn()
      m.register(target('a', 400, 400, { dwellMs: 800, onSelect }))
      const noise = rng(seed)
      let selectedAt: number | null = null
      for (let t = 0; t < 3000; t += FRAME_MS) {
        m.update({ x: 480 + noise() * 30, y: 460 + noise() * 30, t })
        if (onSelect.mock.calls.length > 0 && selectedAt === null) selectedAt = t
      }
      expect(selectedAt, `seed ${seed}`).not.toBeNull()
      expect(selectedAt!).toBeLessThanOrEqual(800 + 300)
    }
  })

  it('a tremor that wanders onto the edge of a small target still selects within dwellMs + 300 ms', () => {
    const m = new DwellManager()
    const onSelect = vi.fn()
    m.register({ id: 'k', rect: { x: 400, y: 400, w: 60, h: 60 }, dwellMs: 800, variant: 'key', onSelect })
    const noise = rng(9)
    let selectedAt: number | null = null
    for (let t = 0; t < 3000; t += FRAME_MS) {
      m.update({ x: 430 + noise() * 30, y: 430 + noise() * 30, t })
      if (onSelect.mock.calls.length > 0 && selectedAt === null) selectedAt = t
    }
    expect(selectedAt).not.toBeNull()
    expect(selectedAt!).toBeLessThanOrEqual(800 + 300)
  })
})

describe('DwellManager: blink and pause', () => {
  it('blinkSelect needs the target to be armed for ≥200 ms', () => {
    const m = new DwellManager()
    const onSelect = vi.fn()
    m.register(target('a', 400, 400, { onSelect }))
    const { clock, hold } = makeRig(m)
    hold(110, 480, 460) // just became active
    expect(m.blinkSelect(clock.t)).toBe(false)
    hold(BLINK_ARM_MS, 480, 460)
    expect(m.blinkSelect(clock.t)).toBe(true)
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('blinkSelect does nothing without an active target', () => {
    const m = new DwellManager()
    m.register(target('a', 400, 400))
    expect(m.blinkSelect(1000)).toBe(false)
  })

  it('setPaused holds progress steady', () => {
    const m = new DwellManager()
    m.register(target('a', 400, 400))
    const { hold } = makeRig(m)
    hold(400, 480, 460)
    const p = m.progressOf('a')
    m.setPaused(true)
    hold(300, 480, 460)
    expect(m.progressOf('a')).toBe(p)
    m.setPaused(false)
    hold(100, 480, 460)
    expect(m.progressOf('a')).toBeGreaterThan(p)
  })
})

describe('confirmDwellMs', () => {
  it('is max(1500, dwellMs*1.5)', () => {
    expect(confirmDwellMs(800)).toBe(1500)
    expect(confirmDwellMs(1200)).toBe(1800)
    expect(confirmDwellMs(2000)).toBe(3000)
  })
})

describe('tracking loss', () => {
  it('cannot complete a partial dwell after a long sample gap', () => {
    const m = new DwellManager(), onSelect = vi.fn()
    m.register(target('a', 0, 0, { onSelect }))
    for (let t = 0; t <= 800; t += 10) m.update({ x: 80, y: 60, t })
    expect(onSelect).not.toHaveBeenCalled()
    m.update({ x: 80, y: 60, t: 5000 })
    expect(m.progressOf('a')).toBe(0)
    expect(onSelect).not.toHaveBeenCalled()
  })
})

describe('click mode (dwell off)', () => {
  it('nothing but STOP selects by dwell; turning dwell back on restores it', () => {
    const m = new DwellManager()
    const card = vi.fn(), stop = vi.fn()
    m.register({ ...target('card', 0, 0), onSelect: card })
    m.register({ ...target('stop', 400, 0, { variant: 'stop', dwellMs: 400 }), onSelect: stop })
    m.setDwellEnabled(false)
    const rig = makeRig(m)
    rig.hold(2000, 80, 60)
    expect(card).not.toHaveBeenCalled()
    expect(m.getState().activeId).toBeNull()
    rig.hold(800, 480, 60)
    expect(stop).toHaveBeenCalledTimes(1)
    m.setDwellEnabled(true)
    rig.hold(1500, 80, 60)
    expect(card).toHaveBeenCalledTimes(1)
  })
})

describe('magnetic targets (head pointing)', () => {
  it('a pointer near, but outside, a target selects it only with the magnet on', () => {
    for (const [magnet, expected] of [[0, 0], [90, 1]] as const) {
      const m = new DwellManager()
      const select = vi.fn()
      m.register({ ...target('card', 0, 0), onSelect: select })
      m.setMagnet(magnet)
      makeRig(m).hold(1500, 160 + 70, 60) // 70 px right of the card's edge
      expect(select, `magnet ${magnet}`).toHaveBeenCalledTimes(expected)
    }
  })

  it('a target under the pointer still beats a nearer magnet; otherwise the nearest edge wins', () => {
    const m = new DwellManager()
    const a = vi.fn(), b = vi.fn()
    m.register({ ...target('a', 0, 0), onSelect: a })
    m.register({ ...target('b', 400, 0), onSelect: b })
    m.setMagnet(90)
    makeRig(m).hold(1500, 400 - 60, 60) // 180 px from a, 60 px from b
    expect(b).toHaveBeenCalledTimes(1)
    expect(a).not.toHaveBeenCalled()
  })

  it('keyboard keys are never magnetic', () => {
    const m = new DwellManager()
    const select = vi.fn()
    m.register({ ...target('k', 0, 0, { variant: 'key' }), onSelect: select })
    m.setMagnet(90)
    makeRig(m).hold(1500, 160 + 50, 60)
    expect(select).not.toHaveBeenCalled()
  })

  it('beyond the magnet distance nothing is selected', () => {
    const m = new DwellManager()
    const select = vi.fn()
    m.register({ ...target('card', 0, 0), onSelect: select })
    m.setMagnet(90)
    makeRig(m).hold(1500, 160 + 150, 60)
    expect(select).not.toHaveBeenCalled()
  })
})
