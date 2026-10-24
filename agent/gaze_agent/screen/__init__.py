"""AX first; sparse trees fall back to window-only OCR."""
from __future__ import annotations
import os
from dataclasses import replace
from gaze_agent.contracts import Snapshot
from gaze_agent.screen import ax


def get_screen() -> Snapshot:
    snapshot, handles = ax.read_snapshot()
    if os.getenv("GAZE_FORCE_OCR") == "1" or sum(bool(e.label) for e in snapshot.elements) < 5:
        from gaze_agent.screen.ocr import read_ocr
        elements = read_ocr()
        if snapshot.focused:
            elements = [snapshot.focused] + elements
        snapshot = replace(snapshot, elements=elements[:150])
    return ax.publish(snapshot, handles)
