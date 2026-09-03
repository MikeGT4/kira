"""Native settings window that reads and writes the YAML config."""
from __future__ import annotations
import json
import logging
import os
import subprocess
import urllib.request
from pathlib import Path
import yaml
import objc
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSBundle,
    NSButton,
    NSButtonTypeSwitch,
    NSComboBox,
    NSFont,
    NSMakeRect,
    NSObject,
    NSPopUpButton,
    NSTextAlignmentRight,
    NSTextField,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from kira.config import load_config

log = logging.getLogger(__name__)

HOTKEYS = ("fn", "alt+space", "ctrl+shift+d")
EDIT_MODIFIERS = ("shift", "ctrl", "alt", "cmd")
EDIT_OFF = "aus"
LANGUAGES = ("auto", "de", "en")
DEFAULT_DEVICE = "Systemstandard"
WIN_W, WIN_H = 540, 420
ROW_H = 34
LABEL_W = 170
FIELD_X = 195
FIELD_W = 320


def merge_settings(raw: dict | None, values: dict[str, object]) -> dict:
    """Return a copy of the raw config dict with dotted keys applied."""
    out = json.loads(json.dumps(raw)) if raw else {}
    for dotted, value in values.items():
        section, key = dotted.split(".", 1)
        section_dict = out.get(section)
        if not isinstance(section_dict, dict):
            section_dict = {}
            out[section] = section_dict
        section_dict[key] = value
    return out


def list_ollama_models(timeout: float = 2.0) -> list[str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=timeout) as resp:
            data = json.load(resp)
        return sorted(m["name"] for m in data.get("models", []))
    except Exception as exc:
        log.info("ollama model list unavailable: %s", exc)
        return []


def list_input_devices() -> list[str]:
    try:
        import sounddevice as sd
        names = []
        for dev in sd.query_devices():
            if dev.get("max_input_channels", 0) > 0 and dev.get("name") not in names:
                names.append(dev.get("name"))
        return names
    except Exception as exc:
        log.info("input device list unavailable: %s", exc)
        return []


def parse_positive_float(text: str) -> float | None:
    try:
        value = float(str(text).replace(",", ".").strip())
    except ValueError:
        return None
    return value if value > 0 else None


class _Actions(NSObject):
    def initWithOwner_(self, owner):
        self = objc.super(_Actions, self).init()
        if self is None:
            return None
        self._owner = owner
        return self

    def save_(self, sender):
        self._owner.save()

    def cancel_(self, sender):
        self._owner.close()


class SettingsWindow:
    """Builds the window lazily and fills it from the config file on every show."""

    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._window = None
        self._actions = None
        self._fields: dict[str, object] = {}

    def show(self) -> None:
        if self._window is None:
            self._build()
        self._fill()
        NSApp.activateIgnoringOtherApps_(True)
        self._window.center()
        self._window.makeKeyAndOrderFront_(None)

    def close(self) -> None:
        if self._window is not None:
            self._window.orderOut_(None)

    def _label(self, content, text: str, y: float) -> None:
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(15, y + 4, LABEL_W, 20))
        field.setStringValue_(text)
        field.setEditable_(False)
        field.setBordered_(False)
        field.setDrawsBackground_(False)
        field.setSelectable_(False)
        field.setAlignment_(NSTextAlignmentRight)
        content.addSubview_(field)

    def _popup(self, content, y: float, titles) -> NSPopUpButton:
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(FIELD_X, y, FIELD_W, 26), False)
        popup.addItemsWithTitles_(list(titles))
        content.addSubview_(popup)
        return popup

    def _combo(self, content, y: float) -> NSComboBox:
        combo = NSComboBox.alloc().initWithFrame_(NSMakeRect(FIELD_X, y, FIELD_W, 26))
        combo.setCompletes_(True)
        content.addSubview_(combo)
        return combo

    def _text(self, content, y: float, width: float = FIELD_W) -> NSTextField:
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(FIELD_X, y, width, 24))
        content.addSubview_(field)
        return field

    def _build(self) -> None:
        rect = NSMakeRect(0, 0, WIN_W, WIN_H)
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskTitled | NSWindowStyleMaskClosable, NSBackingStoreBuffered, False
        )
        self._window.setTitle_("Kira-Einstellungen")
        self._window.setReleasedWhenClosed_(False)
        self._actions = _Actions.alloc().initWithOwner_(self)
        content = self._window.contentView()
        y = WIN_H - 50
        rows = (
            ("Diktat-Taste", "hotkey"),
            ("Bearbeiten mit fn +", "edit"),
            ("Polish-Modell", "model"),
            ("Timeout Diktat (s)", "timeout"),
            ("Timeout Bearbeiten (s)", "edit_timeout"),
            ("Whisper-Modell", "whisper"),
            ("Sprache", "language"),
            ("Mikrofon", "device"),
        )
        for label, key in rows:
            self._label(content, label, y)
            if key == "hotkey":
                self._fields[key] = self._popup(content, y, HOTKEYS)
            elif key == "edit":
                self._fields[key] = self._popup(content, y, EDIT_MODIFIERS + (EDIT_OFF,))
            elif key == "model":
                self._fields[key] = self._combo(content, y)
            elif key == "language":
                self._fields[key] = self._popup(content, y, LANGUAGES)
            elif key == "device":
                self._fields[key] = self._popup(content, y, (DEFAULT_DEVICE,))
            elif key in ("timeout", "edit_timeout"):
                self._fields[key] = self._text(content, y, 90)
            else:
                self._fields[key] = self._text(content, y)
            y -= ROW_H
        hud = NSButton.alloc().initWithFrame_(NSMakeRect(FIELD_X, y, FIELD_W, 24))
        hud.setButtonType_(NSButtonTypeSwitch)
        hud.setTitle_("HUD beim Diktat anzeigen")
        content.addSubview_(hud)
        self._fields["popup"] = hud
        hint = NSTextField.alloc().initWithFrame_(NSMakeRect(15, 18, 180, 20))
        hint.setStringValue_("Speichern startet Kira neu.")
        hint.setEditable_(False)
        hint.setBordered_(False)
        hint.setDrawsBackground_(False)
        hint.setSelectable_(False)
        hint.setFont_(NSFont.systemFontOfSize_(11))
        content.addSubview_(hint)
        cancel = NSButton.alloc().initWithFrame_(NSMakeRect(WIN_W - 340, 12, 100, 32))
        cancel.setTitle_("Abbrechen")
        cancel.setBezelStyle_(NSBezelStyleRounded)
        cancel.setTarget_(self._actions)
        cancel.setAction_("cancel:")
        cancel.setKeyEquivalent_("\x1b")
        content.addSubview_(cancel)
        save = NSButton.alloc().initWithFrame_(NSMakeRect(WIN_W - 230, 12, 215, 32))
        save.setTitle_("Speichern und neu starten")
        save.setBezelStyle_(NSBezelStyleRounded)
        save.setTarget_(self._actions)
        save.setAction_("save:")
        save.setKeyEquivalent_("\r")
        content.addSubview_(save)

    def _fill(self) -> None:
        cfg = load_config(self._path)
        f = self._fields
        f["hotkey"].selectItemWithTitle_(cfg.hotkey.combo if cfg.hotkey.combo in HOTKEYS else HOTKEYS[0])
        f["edit"].selectItemWithTitle_(cfg.hotkey.edit_modifier or EDIT_OFF)
        f["model"].removeAllItems()
        f["model"].addItemsWithObjectValues_(list_ollama_models())
        f["model"].setStringValue_(cfg.styler.model)
        f["timeout"].setStringValue_(f"{cfg.styler.timeout_seconds:g}")
        f["edit_timeout"].setStringValue_(f"{cfg.styler.edit_timeout_seconds:g}")
        f["whisper"].setStringValue_(cfg.whisper.model)
        f["language"].selectItemWithTitle_(cfg.whisper.language)
        f["device"].removeAllItems()
        f["device"].addItemsWithTitles_([DEFAULT_DEVICE] + list_input_devices())
        f["device"].selectItemWithTitle_(cfg.audio.input_device or DEFAULT_DEVICE)
        if f["device"].selectedItem() is None:
            f["device"].selectItemAtIndex_(0)
        f["popup"].setState_(1 if cfg.ui.popup else 0)

    def values(self) -> dict[str, object] | None:
        f = self._fields
        timeout = parse_positive_float(f["timeout"].stringValue())
        edit_timeout = parse_positive_float(f["edit_timeout"].stringValue())
        model = f["model"].stringValue().strip()
        whisper = f["whisper"].stringValue().strip()
        if timeout is None or edit_timeout is None or not model or not whisper:
            return None
        edit = f["edit"].titleOfSelectedItem()
        device = f["device"].titleOfSelectedItem()
        return {
            "hotkey.combo": f["hotkey"].titleOfSelectedItem(),
            "hotkey.edit_modifier": None if edit == EDIT_OFF else edit,
            "styler.model": model,
            "styler.timeout_seconds": timeout,
            "styler.edit_timeout_seconds": edit_timeout,
            "whisper.model": whisper,
            "whisper.language": f["language"].titleOfSelectedItem(),
            "audio.input_device": None if device == DEFAULT_DEVICE else device,
            "ui.popup": bool(f["popup"].state()),
        }

    def save(self) -> None:
        values = self.values()
        if values is None:
            import rumps
            rumps.alert(title="Kira", message="Bitte Modellnamen und Timeouts prüfen.")
            return
        raw = {}
        if self._path.exists():
            raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        merged = merge_settings(raw, values)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")
        log.info("settings saved to %s", self._path)
        self.close()
        relaunch()


def relaunch() -> None:
    """Restart the app bundle; outside a bundle only log the request."""
    bundle = str(NSBundle.mainBundle().bundlePath() or "")
    if bundle.endswith(".app"):
        subprocess.Popen(["/bin/sh", "-c", f"sleep 0.8; open '{bundle}'"])
        os._exit(0)
    log.warning("not running from a bundle, restart Kira by hand")
