// Demo mode only: a soft tick when a target is selected, so the room hears what the user chose.
// Synthesised (no audio files): a short sine blip with a fast attack and a quick decay.

let context: AudioContext | null = null

/** `low` for STOP: a deeper tone that reads as "halt" rather than "chosen". */
export function playSelectTick(low = false): void {
  try {
    context ??= new AudioContext()
    if (context.state === 'suspended') void context.resume()
    const now = context.currentTime
    const osc = context.createOscillator(), gain = context.createGain()
    osc.type = 'sine'
    osc.frequency.setValueAtTime(low ? 330 : 880, now)
    osc.frequency.exponentialRampToValueAtTime(low ? 220 : 660, now + 0.12)
    gain.gain.setValueAtTime(0.0001, now)
    gain.gain.exponentialRampToValueAtTime(0.12, now + 0.008)
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.16)
    osc.connect(gain).connect(context.destination)
    osc.start(now)
    osc.stop(now + 0.18)
  } catch { /* no audio (tests, blocked autoplay): silent */ }
}
