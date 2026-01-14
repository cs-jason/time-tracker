#!/usr/bin/env python3
"""Activity capture for macOS (with graceful degradation)."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

from tt_models import Activity

_IMPORT_ERROR: Optional[Exception] = None
_AX = None

try:
    from AppKit import NSWorkspace
    import Quartz
    try:
        import ApplicationServices as _AX  # type: ignore
    except Exception:
        _AX = Quartz  # type: ignore
except Exception as exc:  # pragma: no cover - non-macOS
    NSWorkspace = None  # type: ignore
    Quartz = None  # type: ignore
    _AX = None
    _IMPORT_ERROR = exc


@dataclass
class PermissionStatus:
    accessibility: Optional[bool]
    automation: Optional[bool]
    screen_recording: Optional[bool]


def permission_status() -> PermissionStatus:
    if Quartz is None or _AX is None:
        return PermissionStatus(None, None, None)
    try:
        trusted = bool(
            _AX.AXIsProcessTrustedWithOptions(
                {_AX.kAXTrustedCheckOptionPrompt: False}
            )
        )
    except Exception:
        trusted = None
    return PermissionStatus(trusted, None, None)

def frameworks_available() -> tuple[bool, Optional[str]]:
    if NSWorkspace is None or Quartz is None or _AX is None:
        if _IMPORT_ERROR:
            return False, str(_IMPORT_ERROR)
        return False, "PyObjC not installed"
    required = [
        "AXUIElementCreateApplication",
        "AXUIElementCopyAttributeValue",
        "kAXFocusedWindowAttribute",
        "kAXTitleAttribute",
        "kAXDocumentAttribute",
        "kAXTrustedCheckOptionPrompt",
    ]
    missing = [name for name in required if not hasattr(_AX, name)]
    cg_required = [
        "CGEventSourceSecondsSinceLastEventType",
        "kCGEventSourceStateCombinedSessionState",
        "kCGAnyInputEventType",
    ]
    missing += [name for name in cg_required if not hasattr(Quartz, name)]
    if missing:
        return False, f"Quartz missing symbols: {', '.join(missing)}"
    return True, None


def get_current_activity(idle_threshold: int) -> Activity:
    if NSWorkspace is None or Quartz is None or _AX is None:
        detail = str(_IMPORT_ERROR) if _IMPORT_ERROR else "PyObjC not installed"
        raise NotImplementedError(f"macOS frameworks not available ({detail})")

    timestamp = datetime.now(timezone.utc)
    app_name, bundle_id, pid = _frontmost_app()
    window_title = _window_title(pid) if pid is not None else None

    doc_value = _ax_document(pid)
    file_path, url_from_doc = _parse_document_value(doc_value)

    url = url_from_doc or _browser_url(app_name)
    if url is None and doc_value and doc_value.startswith("http"):
        url = doc_value

    idle_seconds = _idle_seconds()
    idle = idle_seconds >= idle_threshold

    return Activity(
        timestamp=timestamp,
        app_name=app_name,
        bundle_id=bundle_id,
        window_title=window_title,
        file_path=file_path,
        url=url,
        idle=idle,
    )


def _frontmost_app() -> Tuple[Optional[str], Optional[str], Optional[int]]:
    workspace = NSWorkspace.sharedWorkspace()
    app = workspace.frontmostApplication()
    if app is None:
        return None, None, None
    return app.localizedName(), app.bundleIdentifier(), app.processIdentifier()


def _window_title(pid: Optional[int]) -> Optional[str]:
    if pid is None:
        return None
    try:
        app_elem = _AX.AXUIElementCreateApplication(pid)
        window = _ax_value(
            _AX.AXUIElementCopyAttributeValue(
                app_elem, _AX.kAXFocusedWindowAttribute
            )
        )
        if window is None:
            return None
        title = _ax_value(
            _AX.AXUIElementCopyAttributeValue(window, _AX.kAXTitleAttribute)
        )
        return str(title) if title else None
    except Exception:
        return None


def _ax_document(pid: Optional[int]) -> Optional[str]:
    if pid is None:
        return None
    try:
        app_elem = _AX.AXUIElementCreateApplication(pid)
        window = _ax_value(
            _AX.AXUIElementCopyAttributeValue(
                app_elem, _AX.kAXFocusedWindowAttribute
            )
        )
        if window is None:
            return None
        doc = _ax_value(
            _AX.AXUIElementCopyAttributeValue(window, _AX.kAXDocumentAttribute)
        )
        return str(doc) if doc else None
    except Exception:
        return None


def _ax_value(value):
    if isinstance(value, tuple) and len(value) == 2:
        return value[1]
    return value


def _parse_document_value(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not value:
        return None, None
    if value.startswith("file://"):
        path = value.replace("file://", "", 1)
        return path, None
    if value.startswith("/"):
        return value, None
    if value.startswith("http"):
        return None, value
    return None, None


def _browser_url(app_name: Optional[str]) -> Optional[str]:
    if not app_name:
        return None

    script = None
    if app_name == "Safari":
        script = (
            'tell application "Safari" to if (count of documents) > 0 then ' 
            'get URL of front document'
        )
    elif app_name in {
        "Google Chrome",
        "Google Chrome Canary",
        "Brave Browser",
        "Microsoft Edge",
        "Vivaldi",
        "Opera",
    }:
        script = (
            f'tell application "{app_name}" to '
            'get URL of active tab of front window'
        )
    elif app_name == "Arc":
        script = 'tell application "Arc" to get URL of active tab of front window'
    elif app_name in {"Firefox", "Firefox Developer Edition"}:
        script = None

    if not script:
        return None
    return _run_osascript(script)


def _run_osascript(script: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    value = result.stdout.strip()
    return value if value else None


def _idle_seconds() -> float:
    try:
        return float(
            Quartz.CGEventSourceSecondsSinceLastEventType(
                Quartz.kCGEventSourceStateCombinedSessionState,
                Quartz.kCGAnyInputEventType,
            )
        )
    except Exception:
        return 0.0
