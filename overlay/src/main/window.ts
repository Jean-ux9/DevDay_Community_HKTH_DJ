import type { WindowPolicy } from '../shared/app'
/** Confirm is the sole task-time exception; STOP and the pill remain click-through. */
export const ignoreMouse = (policy: WindowPolicy): boolean =>
  !policy.confirming && (policy.taskActive || !policy.caregiverHover)
export const STOP_HOTKEY = 'Control+Alt+Command+.'
export const MOUSE_HOTKEY = 'Control+Alt+Command+M'
/** Click mode: dwell off except STOP, so a mouse used as gaze stops selecting everything it crosses. */
export const CLICK_HOTKEY = 'Control+Alt+Command+D'
export const QUIT_HOTKEY = 'Control+Alt+Command+Q'
/** Switches between custom calibration (default) and macOS Head Pointer driving the cursor. */
export const HEAD_POINTER_HOTKEY = 'Command+Alt+P'
