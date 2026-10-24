"""Apple Vision text recognition on the target window only."""
from __future__ import annotations

import math

from gaze_agent.contracts import Element
from gaze_agent.screen.shot import TargetWindow, capture_window, target_window


def screen_bbox(box: tuple[float, float, float, float], target: TargetWindow) -> tuple[int, int, int, int]:
    """Vision is normalized with bottom-left origin; AX uses screen top-left."""
    x, y, width, height = box
    if not all(math.isfinite(v) for v in box) or width <= 0 or height <= 0:
        raise ValueError("Invalid OCR box")
    left, right = max(0, min(1, x)), max(0, min(1, x + width))
    top, bottom = max(0, min(1, 1 - y - height)), max(0, min(1, 1 - y))
    left, right = round(left * target.width), round(right * target.width)
    top, bottom = round(top * target.height), round(bottom * target.height)
    if right <= left or bottom <= top:
        raise ValueError("OCR box is outside the target window")
    return target.x + left, target.y + top, right - left, bottom - top


def recognize(raw: bytes, target: TargetWindow, *, fast: bool = False) -> list[Element]:
    import Vision
    from Foundation import NSData
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast if fast
                                 else Vision.VNRequestTextRecognitionLevelAccurate)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
        NSData.dataWithBytes_length_(raw, len(raw)), {})
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"OCR failed: {error}")
    elements = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        rect = observation.boundingBox()
        label = " ".join(str(candidates[0].string()).split())
        if not label:
            continue
        try:
            bbox = screen_bbox((rect.origin.x, rect.origin.y, rect.size.width, rect.size.height), target)
        except ValueError:
            continue
        elements.append(Element(f"o{len(elements) + 1}", "text", label, "", True, bbox, "ocr"))
        if len(elements) >= 150:
            break
    return elements


def read_ocr() -> list[Element]:
    target = target_window()
    return recognize(capture_window(target), target)
