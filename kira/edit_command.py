"""Selection-Capture für AI-Editing-Commands (F9-Pfad).

Flow (Windows):
1. read_selection() schickt Strg+C an die fokussierte App, wartet
   kurz, liest das Clipboard. Wenn das Clipboard leer bleibt
   (= keine Selection aktiv), Return None.
2. KiraApp wechselt in EDIT-Mode, recordet den Voice-Command.
3. Whisper transkribiert den Command.
4. Styler.edit_command(selection, command) ruft Ollama mit dem
   prompts/edit_command.md Template, das beide Inputs einsetzt.
5. Standard-Injector pasted das Output: weil die Selection in der
   Ziel-App noch aktiv ist, ersetzt Strg+V sie automatisch.

Empty-Detection: Clipboard wird vor Strg+C auf "" gesetzt. Wenn der
String leer bleibt, hat Strg+C nichts gefunden — bewusst KEIN
Sentinel-String mehr, weil Clipboard-Watcher (Ditto, ClipboardFusion,
Discord-emoji-picker) den Sentinel sonst als History-Eintrag
persistieren wuerden (code-reviewer 2026-05-09).

Failure-Modes: Clipboard-Operationen koennen unter Windows-RDP-Shimmer
oder bei kompetierender Clipboard-Locking transient fehlschlagen. Die
Funktion unterscheidet "keine Selection" (return None) von "Clipboard
nicht erreichbar" (raise ClipboardUnavailable) — nur so kann der Caller
dem User echtes Fehler-Feedback geben statt ein stilles No-Op.
"""
from __future__ import annotations
import logging
import time
import keyboard
import pyperclip

log = logging.getLogger(__name__)


class ClipboardUnavailable(RuntimeError):
    """Clipboard ist nicht zugreifbar (RDP-Shimmer, andere App haelt
    OpenClipboard, Treiber-Hang). Caller soll User-sichtbar berichten —
    NICHT als 'keine Selection' interpretieren."""


# 100 ms reichen empirisch fuer alle Apps die ich getestet habe (Word,
# VS Code, Chrome, Slack-Web, Notepad). Manche Editor-Plugins blocken
# Strg+C kurz, dann brauchen wir mehr — der Injector hat denselben
# 20-ms-Settle nach Set, wir geben hier 100 ms.
_CTRL_C_SETTLE_MS = 100


def read_selection() -> str | None:
    """Capture the current selection via Strg+C round-trip.

    Returns:
        Selected text, or None if nothing is selected.

    Raises:
        ClipboardUnavailable: bei pyperclip- oder keyboard-Fehlern. Der
            Caller MUSS das fangen und dem User signalisieren — sonst
            sehen Mike's User keinen Unterschied zwischen "Clipboard
            kaputt" und "keine Selection markiert".
    """
    try:
        saved = pyperclip.paste()
    except Exception as exc:
        raise ClipboardUnavailable(
            f"Clipboard-Lesen vor Strg+C fehlgeschlagen: {exc}"
        ) from exc

    try:
        pyperclip.copy("")  # leeren statt Sentinel — kein Pollution-Effekt
    except Exception as exc:
        raise ClipboardUnavailable(
            f"Clipboard-Schreiben (clear) fehlgeschlagen: {exc}"
        ) from exc

    try:
        keyboard.send("ctrl+c")
    except Exception as exc:
        # Cleanup VOR dem Throw: Clipboard auf den Original-Inhalt
        # zuruecksetzen, sonst hat der User unsere Leerung permanent.
        try:
            pyperclip.copy(saved)
        except Exception:
            pass
        raise ClipboardUnavailable(
            f"keyboard.send(ctrl+c) fehlgeschlagen: {exc}"
        ) from exc

    time.sleep(_CTRL_C_SETTLE_MS / 1000.0)

    try:
        result = pyperclip.paste()
    except Exception as exc:
        try:
            pyperclip.copy(saved)
        except Exception:
            pass
        raise ClipboardUnavailable(
            f"Clipboard-Lesen nach Strg+C fehlgeschlagen: {exc}"
        ) from exc

    # Restore das ursprüngliche Clipboard. Auch wenn die Selection
    # leer war, restoriert das den Original-Inhalt — kein Datenverlust.
    try:
        pyperclip.copy(saved)
    except Exception:
        log.warning("clipboard restore after selection-capture failed")

    if not result:
        log.info("read_selection: no selection (Strg+C did not change clipboard)")
        return None
    log.info("read_selection: captured %d chars", len(result))
    return result
