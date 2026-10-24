"""Apple Vision text recognition on the target window only."""
from __future__ import annotations

from gaze_agent.contracts import Element
from gaze_agent.screen.shot import TargetWindow, capture_window, target_window


def screen_bbox(box: tuple[float, float, float, float], target: TargetWindow) -> tuple[int, int, int, int]:
    """Vision is normalized with bottom-left origin; AX uses screen top-left."""
    x, y, width, height = box
    return (target.x + round(x * target.width), target.y + round((1 - y - height) * target.height),
            round(width * target.width), round(height * target.height))


def recognize(raw: bytes, target: TargetWindow) -> list[Element]:
    import Vision
    from Foundation import NSData
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
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
        bbox = screen_bbox((rect.origin.x, rect.origin.y, rect.size.width, rect.size.height), target)
        elements.append(Element(f"o{len(elements) + 1}", "text", str(candidates[0].string()), "", True, bbox, "ocr"))
        if len(elements) >= 150:
            break
    return elements


def read_ocr() -> list[Element]:
    target = target_window()
    return recognize(capture_window(target), target)
