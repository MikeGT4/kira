"""Selection-Capture fuer AI-Editing-Commands (F9-Pfad).

Flow (Windows):
1. read_selection() schickt Strg+C an die fokussierte App, wartet
   kurz, liest das Clipboard. Wenn das Clipboard sich nicht aendert
   (= keine Selection aktiv), Return None.
2. KiraApp wechselt in EDIT-Mode, recordet den Voice-Command.
3. Whisper transkribiert den Command.
4. Styler.edit_command(selection, command) ruft Ollama mit dem
   prompts/edit_command.md Template, das beide Inputs einsetzt.
5. Standard-Injector pasted das Output: weil die Selection in der
   Ziel-App noch aktiv ist, ersetzt Strg+V sie automatisch.

Sentinel-basierte Empty-Detection: vor Strg+C setzen wir das Clipboard
auf einen unwahrscheinlich kollidierenden Marker. Wenn der Marker
unveraendert wieder rauskommt, hat Strg+C nichts gefunden (= keine
Selection). Ohne den Sentinel waere "Selection identisch zum vorigen
Clipboard" nicht von "keine Selection" zu unterscheiden.
"""
from __future__ import annotations
import logging
import time
import keyboard
import pyperclip

log = logging.getLogger(__name__)

_EMPTY_SENTINEL = "__KIRA_EDIT_NO_SELECTION__"
# 100 ms reichen empirisch fuer alle Apps die ich getestet habe (Word,
# VS Code, Chrome, Slack-Web, Notepad). Manche Editor-Plugins blocken
# Strg+C kurz, dann brauchen wir mehr — der Injector hat denselben
# 20-ms-Settle nach Set, wir geben hier 100 ms.
_CTRL_C_SETTLE_MS = 100


def read_selection() -> str | None:
    """Capture the current selection via Strg+C round-trip.

    Returns:
        Selected text, or None if nothing is selected (or Clipboard-
        Access fehlschlaegt). Restoriert das urspruengliche Clipboard
        nach dem Read, sodass nachgelagerte Inject-Calls darauf bauen
        koennen.
    """
    try:
        saved = pyperclip.paste()
    except Exception:
        log.warning("pyperclip.paste failed before Strg+C; aborting selection read")
        return None

    try:
        pyperclip.copy(_EMPTY_SENTINEL)
    except Exception:
        log.exception("pyperclip.copy sentinel failed")
        return None

    try:
        keyboard.send("ctrl+c")
    except Exception:
        log.exception("keyboard.send(ctrl+c) failed")
        # Restore und abort — wir haben gerade den Sentinel gesetzt,
        # MUST aufraeumen sonst hat der User Garbage im Clipboard.
        try:
            pyperclip.copy(saved)
        except Exception:
            pass
        return None

    time.sleep(_CTRL_C_SETTLE_MS / 1000.0)

    try:
        result = pyperclip.paste()
    except Exception:
        log.warning("pyperclip.paste after Strg+C failed")
        result = _EMPTY_SENTINEL  # treat as empty + restore below

    # Restore das urspruengliche Clipboard. Auch wenn die Selection
    # gleich dem alten Clipboard war (false-negative), restoriert das
    # trotzdem — kein Datenverlust. Falls Strg+C aktiv eine NEUE
    # Selection ins Clipboard kopiert hat, restoriert das die alte.
    try:
        pyperclip.copy(saved)
    except Exception:
        log.warning("clipboard restore after selection-capture failed")

    if result == _EMPTY_SENTINEL or not result:
        log.info("read_selection: no selection (Strg+C did not change clipboard)")
        return None
    log.info("read_selection: captured %d chars", len(result))
    return result
