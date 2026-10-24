import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from gaze_agent import auto, screen
from gaze_agent.screen import ax, ocr, shot
from tests.runtime.support import SEND, SNAPSHOT


def setup_ocr(monkeypatch):
    now = [0.0]
    attempts, recognized = [], []
    limiter = shot.AutoOCR(clock=lambda: now[0])
    monkeypatch.setattr(shot, "auto_ocr", limiter)
    monkeypatch.setattr(shot, "target_window", lambda: shot.TargetWindow(42, 400, 200, 1000, 500))
    def capture(target):
        attempts.append(now[0])
        return b"fake-raw"
    monkeypatch.setattr(shot, "capture_window", capture)
    monkeypatch.setattr(shot, "vision_image", lambda raw: (b"fake-downscaled", (1000, 500)))
    text = replace(SEND, id="o1", label="OCR text", source="ocr")
    def recognize(raw, target, *, fast=False):
        recognized.append((raw, fast))
        return [text]
    monkeypatch.setattr(ocr, "recognize", recognize)
    return now, attempts, recognized, text


def test_capture_budget_and_same_normalized_window_reuse(monkeypatch):
    now, attempts, recognized, text = setup_ocr(monkeypatch)
    labels = [replace(SEND, id=f"e{i}", label="x" * 15) for i in range(2)]
    snapshot = replace(SNAPSHOT, focused=None, elements=labels, window_title="Inbox (3)")
    monkeypatch.setattr(ax, "read_snapshot", lambda: (snapshot, {}))
    assert screen.get_screen(auto=True).elements == labels + [text]
    now[0] = 59
    snapshot = replace(snapshot, window_title="Inbox (4)")
    assert screen.get_screen(auto=True).elements == labels + [text]
    snapshot = replace(snapshot, window_title="Sent")
    assert screen.get_screen(auto=True).elements == labels
    now[0] = 60
    assert screen.get_screen(auto=True).elements == labels + [text]
    assert attempts == [0, 60] and recognized == [(b"fake-downscaled", True)] * 2


@pytest.mark.parametrize("count,length", [(3, 1), (5, 1), (2, 40), (1, 80)])
def test_auto_thresholds_ignore_force_ocr(monkeypatch, count, length):
    _, attempts, _, _ = setup_ocr(monkeypatch)
    monkeypatch.setenv("GAZE_FORCE_OCR", "1")
    snapshot = replace(SNAPSHOT, elements=[replace(SEND, id=f"e{i}", label="x" * length) for i in range(count)])
    monkeypatch.setattr(ax, "read_snapshot", lambda: (snapshot, {}))
    assert screen.get_screen(auto=True) == snapshot and not attempts


def test_capture_failure_consumes_budget_across_windows(monkeypatch):
    now, attempts, _, _ = setup_ocr(monkeypatch)
    def fail(target):
        attempts.append(now[0])
        raise RuntimeError("fake capture failure")
    monkeypatch.setattr(shot, "capture_window", fail)
    assert shot.auto_ocr.read("app|Inbox") == []
    now[0] = 59
    assert shot.auto_ocr.read("app|Sent") == []
    now[0] = 60
    assert shot.auto_ocr.read("app|Sent") == []
    assert attempts == [0, 60]


def test_type_and_tasks_keep_original_ocr_threshold(monkeypatch):
    labels = [replace(SEND, id=f"e{i}") for i in range(4)]
    snapshot = replace(SNAPSHOT, elements=labels, focused=None)
    monkeypatch.setattr(ax, "read_snapshot", lambda: (snapshot, {}))
    calls = []
    monkeypatch.setattr(ocr, "read_ocr", lambda: calls.append(True) or [SEND])
    assert screen.get_screen().elements == [SEND] and calls == [True]
    assert screen.get_screen(auto=True) == snapshot and calls == [True]


def test_production_watcher_uses_auto_screen_path(monkeypatch, persona):
    _, attempts, _, _ = setup_ocr(monkeypatch)
    snapshot = replace(SNAPSHOT, elements=[replace(SEND, id=f"e{i}") for i in range(4)])
    monkeypatch.setattr(ax, "read_snapshot", lambda: (snapshot, {}))
    def forbidden():
        raise AssertionError("Auto must not use the task OCR policy")
    monkeypatch.setattr(ocr, "read_ocr", forbidden)
    watcher = auto.AutoWatcher(None, None, screen.get_screen, lambda: persona)
    assert watcher.get_screen() == snapshot and not attempts


def test_sips_downscales_to_jpeg_before_ocr(monkeypatch):
    converter = shot.vision_image
    _, _, recognized, _ = setup_ocr(monkeypatch)
    # Exercise the real converter with fake subprocess and image metadata only.
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert args[:9] == ["sips", "-Z", "1280", "-s", "format", "jpeg", "-s", "formatOptions", "70"]
        Path(args[-1]).write_bytes(b"fake-downscaled")
    monkeypatch.setattr(shot.subprocess, "run", run)
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(NSData=SimpleNamespace(dataWithBytes_length_=lambda raw, size: raw)))
    rep = SimpleNamespace(pixelsWide=lambda: 1280, pixelsHigh=lambda: 640)
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(NSBitmapImageRep=SimpleNamespace(imageRepWithData_=lambda raw: rep)))
    monkeypatch.setattr(shot, "target_window", lambda: shot.TargetWindow(42, 400, 200, 2560, 1280))
    monkeypatch.setattr(shot, "capture_window", lambda target: b"fake-raw")
    monkeypatch.setattr(shot, "vision_image", converter)
    limiter = shot.AutoOCR(clock=lambda: 0)
    limiter.read("app|Inbox")
    assert len(calls) == 1 and recognized == [(b"fake-downscaled", True)]
    assert not Path(calls[0][-1]).exists()


@pytest.mark.parametrize("fast,level", [(True, "fast"), (False, "accurate")])
def test_vision_recognition_level(monkeypatch, fast, level):
    levels = []
    request = SimpleNamespace(setRecognitionLevel_=levels.append, results=lambda: [])
    handler = SimpleNamespace(performRequests_error_=lambda requests, error: (True, None))
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(NSData=SimpleNamespace(dataWithBytes_length_=lambda raw, size: raw)))
    monkeypatch.setitem(sys.modules, "Vision", SimpleNamespace(
        VNRequestTextRecognitionLevelFast="fast", VNRequestTextRecognitionLevelAccurate="accurate",
        VNRecognizeTextRequest=SimpleNamespace(alloc=lambda: SimpleNamespace(init=lambda: request)),
        VNImageRequestHandler=SimpleNamespace(alloc=lambda: SimpleNamespace(initWithData_options_=lambda raw, options: handler))))
    assert ocr.recognize(b"fake-jpeg", shot.TargetWindow(42, 0, 0, 800, 600), fast=fast) == []
    assert levels == [level]
