"""Detect the frontmost macOS app and map to a style mode."""
from __future__ import annotations
import logging
from kira.config import Config

log = logging.getLogger(__name__)


def active_app_bundle_id() -> str | None:
    """Return bundle id of the frontmost app via NSWorkspace."""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        bundle = app.bundleIdentifier()
        return str(bundle) if bundle else None
    except Exception as exc:
        log.warning("active_app_bundle_id error: %s", exc)
        return None


def detect_mode(config: Config) -> str:
    """Return the style mode for the current frontmost app."""
    bundle = active_app_bundle_id()
    if bundle is None:
        return "plain"
    return config.context_modes.get(bundle, "plain")
