// Pacing for the dwell fill (styles/dwell.css): a grey-white fill that sweeps across a target from
// left to right and is full exactly when the dwell completes.

/** CSS cubic-bezier(x1, y1, x2, y2) as a function of x in 0..1. */
export function cubicBezier(x1: number, y1: number, x2: number, y2: number): (x: number) => number {
  const at = (a: number, b: number, t: number) => 3 * a * t * (1 - t) * (1 - t) + 3 * b * t * t * (1 - t) + t * t * t
  return x => {
    if (x <= 0) return 0
    if (x >= 1) return 1
    let lo = 0, hi = 1
    for (let i = 0; i < 24; i++) { const t = (lo + hi) / 2; if (at(x1, x2, t) < x) lo = t; else hi = t }
    return at(y1, y2, (lo + hi) / 2)
  }
}

/** Ease-in-out quad (easings.net): the fill speeds up, then slows into the finish, without a slow
 *  start. Starts at 0 and ends at 1, so the fill still takes exactly the dwell time. */
export const traceEase = cubicBezier(0.45, 0, 0.55, 1)
