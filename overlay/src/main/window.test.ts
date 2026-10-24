import { describe, expect, it } from 'vitest'
import { ignoreMouse } from './window'
describe('click-through window policy', () => {
  it('passes all mouse input through while running, including hover on STOP and pill', () => {
    expect(ignoreMouse({ taskActive: true, confirming: false, caregiverHover: true })).toBe(true)
  })
  it('only captures caregiver controls at idle and the confirm exception', () => {
    expect(ignoreMouse({ taskActive: false, confirming: false, caregiverHover: false })).toBe(true)
    expect(ignoreMouse({ taskActive: false, confirming: false, caregiverHover: true })).toBe(false)
    expect(ignoreMouse({ taskActive: true, confirming: true, caregiverHover: false })).toBe(false)
  })
})
