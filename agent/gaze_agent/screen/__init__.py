"""AX first; sparse trees fall back to window-only OCR."""
from __future__ import annotations
import os
from dataclasses import replace
from gaze_agent.contracts import Snapshot
from gaze_agent.screen import ax


def get_screen(*, auto: bool = False) -> Snapshot:
    snapshot, handles = ax.read_snapshot()
    labels = [e.label.strip() for e in snapshot.elements if e.label.strip()]
    sparse = len(labels) < 3 and sum(map(len, labels)) < 80
    if (auto and sparse) or (not auto and (os.getenv("GAZE_FORCE_OCR") == "1"
                                          or sum(bool(e.label) for e in snapshot.elements) < 5)):
        if auto:
            from gaze_agent.screen.shot import auto_ocr
            elements = auto_ocr.read(snapshot.bundle_id + "|" + snapshot.window_title)
            # Keep useful AX text if capture is limited or failed.
            elements = snapshot.elements + elements
        else:
            from gaze_agent.screen.ocr import read_ocr
            elements = read_ocr()
        if snapshot.focused:
            if auto:
                elements = [e for e in elements if e.id != snapshot.focused.id]
            elements = [snapshot.focused] + elements
        snapshot = replace(snapshot, elements=elements[:150])
    return ax.publish(snapshot, handles)
