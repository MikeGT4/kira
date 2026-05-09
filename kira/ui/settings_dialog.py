"""Form-based settings dialog — replaces 'Open Config…' (Notepad on YAML).

Exposes the runtime knobs users actually tweak (mic gain, mic device,
Whisper language, polish model, polish timeout, clipboard-restore,
hotkey) plus a one-click Polish-Modell-Update via Ollama pull.

Designed to be safe with Mike's lessons-learned comments in
%APPDATA%\\Kira\\config.yaml: writes are routed through
kira.config_writer.update_scalars which preserves comments and blank
lines verbatim. Power users can fall back to 'Rohconfig öffnen…' for
multi-line values (initial_prompt, context_modes, whisper.model path).
"""
from __future__ import annotations
import logging
import subprocess
from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressDialog,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from kira.ui._dialog_style import (
    apply_light_theme,
    light_critical,
    light_information,
    light_warning,
)

from kira.config import default_config_path, load_config
from kira.config_writer import update_scalars

log = logging.getLogger(__name__)
_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"

# userData-Sentinel für den "Windows-Default"-Combobox-Eintrag. Speichert
# beim _save() als input_device=None (= leerer String in der alten
# QLineEdit-Variante).
_DEVICE_DEFAULT_LABEL = "Windows-Default (automatisch)"


class _SectionCard(QWidget):
    """Win11-Settings-style Section-Card.

    Layout:
        Section-Header (kleines Icon + Bold-Title)
        ───────────────────────────────────────────
        QFormLayout(label-rechts | widget-links)

    Visual: weißer Hintergrund, dünner #e0e0e0-Border, 12 px Padding.
    Form-Spacing locker (vertical=10), damit das Layout nicht so
    gequetscht wirkt wie die alte single-form-Variante.
    """

    def __init__(self, title: str, icon_emoji: str = "") -> None:
        super().__init__()
        self.setObjectName("kiraSectionCard")
        # Stylesheet auf das objectName scopen, sonst erbt das alle
        # Children und ueberschreibt z.B. QComboBox-Backgrounds.
        self.setStyleSheet(
            "QWidget#kiraSectionCard { "
            "background: #fbfbfb; "
            "border: 1px solid #e2e2e2; "
            "border-radius: 6px; "
            "}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(8)

        # Header
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        if icon_emoji:
            icon_lbl = QLabel(icon_emoji)
            icon_font = QFont()
            icon_font.setPointSize(13)
            icon_lbl.setFont(icon_font)
            header_row.addWidget(icon_lbl)
        title_lbl = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        header_row.addWidget(title_lbl)
        header_row.addStretch()
        outer.addLayout(header_row)

        # Trenn-Linie unter dem Header
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #ececec;")
        sep.setFixedHeight(1)
        outer.addWidget(sep)

        # Form
        self._form = QFormLayout()
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._form.setHorizontalSpacing(14)
        self._form.setVerticalSpacing(10)
        self._form.setContentsMargins(0, 4, 0, 0)
        outer.addLayout(self._form)

    def add_row(self, label: str, widget_or_layout) -> None:
        """Add a label+widget pair. Label is rendered in regular weight
        (not bold) — bold is reserved for the section header to keep the
        visual hierarchy clear."""
        self._form.addRow(label, widget_or_layout)


def _load_branded_pixmap(size: int) -> QPixmap | None:
    """Load the largest frame from icon-branded.ico and downscale via
    Pillow's LANCZOS to ``size``. QPixmap's native ICO loader picks an
    arbitrary (often 16x16) frame and upscales it to whatever size we
    request — that's what produced the blurry header logo. Pillow lets
    us pick the 256x256 frame explicitly, then downscale once with a
    proper resampling filter, so the result stays crisp at 48 px.
    """
    src = _ASSETS / "icon-branded.ico"
    if not src.exists():
        return None
    try:
        img = Image.open(src)
        ico = getattr(img, "ico", None)
        if ico is not None:
            sizes = sorted(ico.sizes(), key=lambda s: s[0] * s[1])
            if sizes:
                img.size = sizes[-1]  # type: ignore[misc]
                img.load()
        img = img.convert("RGBA").resize(
            (size, size), Image.Resampling.LANCZOS,
        )
        return QPixmap.fromImage(ImageQt(img))
    except Exception:
        log.exception("failed to load icon-branded.ico for header")
        return None


class _PullWorker(QObject):
    """Background ollama.pull(model) — streams events back to the GUI."""
    progress = pyqtSignal(str, int, int)   # status, completed, total
    finished = pyqtSignal(bool, str)       # success, message

    def __init__(self, model_name: str) -> None:
        super().__init__()
        self._model = model_name

    def run(self) -> None:
        try:
            import ollama
        except Exception as e:
            self.finished.emit(False, f"ollama-Library nicht verfügbar: {e}")
            return
        try:
            for event in ollama.pull(self._model, stream=True):
                status = getattr(event, "status", None) or (
                    event.get("status", "") if isinstance(event, dict) else ""
                )
                completed = (
                    getattr(event, "completed", None)
                    or (event.get("completed", 0) if isinstance(event, dict) else 0)
                    or 0
                )
                total = (
                    getattr(event, "total", None)
                    or (event.get("total", 0) if isinstance(event, dict) else 0)
                    or 0
                )
                self.progress.emit(str(status), int(completed), int(total))
            self.finished.emit(True, f"{self._model} ist auf dem aktuellen Stand.")
        except Exception as e:
            log.exception("ollama.pull failed")
            self.finished.emit(False, f"Modell-Update fehlgeschlagen: {e}")


_MINIMAL_CONFIG = """\
# Kira config — auto-generated by Settings dialog.
# Open this file directly for advanced fields (initial_prompt,
# context_modes, whisper.model path, replacements, styler.modes).
audio:
  input_gain: 1.0
  input_device: null
whisper:
  language: auto
styler:
  model: gemma3:12b
  timeout_seconds: 30.0
injector:
  restore_clipboard_after_ms: 500
hotkey:
  combo: f8
  edit_combo: f9
"""


class SettingsDialog(QDialog):
    """Runtime settings + Polish-Modell update."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Kira-Einstellungen")
        icon_path = _ASSETS / "icon-branded.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumWidth(560)
        self.setModal(True)
        apply_light_theme(self)

        self._cfg = load_config()
        self._cfg_path = default_config_path()
        self._pull_thread: QThread | None = None
        self._pull_worker: _PullWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_form())
        outer.addWidget(self._build_hint())
        outer.addLayout(self._build_raw_button_row())
        outer.addWidget(self._build_button_box())

    # ----- builders ------------------------------------------------------

    def _build_header(self) -> QWidget:
        # Kira-branded-Icon links (gelber Rounded-Square + 煌), Title mittig,
        # digitalroots-Logo rechts. Spiegelt das Branding aus den anderen
        # Dialogen wider, aber etwas kompakter — Settings ist ein Werkzeug-
        # Dialog, kein Empfangsschirm, also schmaler Header (~52 px).
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 4)
        row.setSpacing(12)

        kira_label = QLabel()
        kira_pix = _load_branded_pixmap(48)
        if kira_pix is not None:
            kira_label.setPixmap(kira_pix)
        row.addWidget(kira_label)

        row.addStretch()

        title = QLabel("Kira-Einstellungen")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        row.addWidget(title)

        row.addStretch()

        dr_label = QLabel()
        dr_logo = _ASSETS / "digitalroots-logo.png"
        if dr_logo.exists():
            dr_pix = QPixmap(str(dr_logo)).scaledToHeight(
                26, Qt.TransformationMode.SmoothTransformation,
            )
            dr_label.setPixmap(dr_pix)
        row.addWidget(dr_label)

        # dünne Trennlinie unter dem Header
        wrapper = QWidget()
        wrap = QVBoxLayout(wrapper)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(8)
        wrap.addWidget(host)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setStyleSheet("color: #d8d8d8;")
        wrap.addWidget(sep)
        return wrapper

    def _build_form(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)
        layout.addWidget(self._build_section_audio())
        layout.addWidget(self._build_section_whisper())
        layout.addWidget(self._build_section_polish())
        layout.addWidget(self._build_section_hotkeys())
        layout.addWidget(self._build_section_injector())
        return host

    def _build_section_audio(self) -> _SectionCard:
        card = _SectionCard("Audio", icon_emoji="\U0001F3A4")  # mic emoji

        self._gain = QDoubleSpinBox()
        self._gain.setRange(0.1, 200.0)
        self._gain.setSingleStep(0.5)
        self._gain.setDecimals(1)
        self._gain.setValue(self._cfg.audio.input_gain)
        self._gain.setToolTip(
            "Software-Gain auf das rohe Mic-Signal.\n"
            "Sweet Spot: peak 0.3-0.9, rms 0.05-0.15 (siehe kira.log)."
        )
        card.add_row("Mic-Gain", self._gain)

        # Mic-Auswahl als Dropdown: alle Inputs aus sd.query_devices()
        # mit max_input_channels > 0, plus ein Default-Eintrag für
        # input_device=None. Wir speichern den NAMEN (nicht den Index),
        # weil PortAudio-Indizes nach jedem USB-Stecker-Event neu
        # vergeben werden — der Substring-Match in
        # Recorder._resolve_device() ist dagegen stabil.
        mic_box = QVBoxLayout()
        mic_box.setSpacing(4)
        mic_row = QHBoxLayout()
        self._device = QComboBox()
        self._device.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon,
        )
        self._device.setMinimumContentsLength(40)
        self._device.setToolTip(
            "Mikrofon-Auswahl. Gespeichert wird der Name (Substring-Match) -\n"
            "auch nach USB-Neustecken erkennt Kira denselben Eintrag wieder,\n"
            "selbst wenn der PortAudio-Index sich aendert.\n"
            "'Windows-Default' laesst Windows entscheiden - kann durch\n"
            "Noise-Cancel-Filter (ASUS, Nahimic) routen und Whisper-Quality killen."
        )
        mic_row.addWidget(self._device, 1)
        refresh_btn = QPushButton("Aktualisieren")
        refresh_btn.setToolTip(
            "Geraete neu abfragen - nutzen wenn ein Mikro eingesteckt wurde\n"
            "waehrend dieser Dialog offen ist."
        )
        refresh_btn.clicked.connect(self._refresh_devices)
        mic_row.addWidget(refresh_btn)
        mic_box.addLayout(mic_row)
        self._device_hint = QLabel("")
        self._device_hint.setStyleSheet("color: #c4793a; font-size: 11px;")
        self._device_hint.setWordWrap(True)
        self._device_hint.setVisible(False)
        mic_box.addWidget(self._device_hint)
        self._populate_device_combo(self._cfg.audio.input_device)
        card.add_row("Mikrofon", mic_box)

        return card

    def _build_section_whisper(self) -> _SectionCard:
        card = _SectionCard("Whisper", icon_emoji="\U0001F4DD")  # memo emoji

        self._language = QComboBox()
        self._language.addItems(["auto", "de", "en"])
        self._language.setCurrentText(self._cfg.whisper.language)
        self._language.setToolTip(
            "auto = Whisper erkennt die Sprache pro Recording. de/en\n"
            "fixiert -> ~5%% bessere Accuracy bei sauberen Mono-Sprache-Sessions."
        )
        card.add_row("Sprache", self._language)

        return card

    def _build_section_polish(self) -> _SectionCard:
        card = _SectionCard("Polish-LLM", icon_emoji="✨")  # sparkles emoji

        polish_row = QHBoxLayout()
        self._styler_model = QLineEdit()
        self._styler_model.setText(self._cfg.styler.model)
        self._styler_model.setPlaceholderText("z.B. gemma3:12b, qwen3:8b")
        polish_row.addWidget(self._styler_model)
        update_btn = QPushButton("Aktualisieren")
        update_btn.setToolTip(
            "Laedt das aktuelle Polish-Modell neu via ollama pull -\n"
            "z.B. nachdem die Ollama-Library eine neue Modell-Version\n"
            "veroeffentlicht hat."
        )
        update_btn.clicked.connect(self._update_polish_model)
        polish_row.addWidget(update_btn)
        card.add_row("Modell", polish_row)

        self._styler_timeout = QDoubleSpinBox()
        self._styler_timeout.setRange(1.0, 120.0)
        self._styler_timeout.setSingleStep(1.0)
        self._styler_timeout.setDecimals(1)
        self._styler_timeout.setSuffix(" s")
        self._styler_timeout.setValue(self._cfg.styler.timeout_seconds)
        self._styler_timeout.setToolTip(
            "Timeout fuer den Polish-API-Call. 30 s ist robust fuer 12B-\n"
            "Modelle im Cold-Start; 5 s reicht fuer warm gehaltene 2B-Modelle."
        )
        card.add_row("Timeout", self._styler_timeout)

        return card

    def _build_section_hotkeys(self) -> _SectionCard:
        card = _SectionCard("Hotkeys", icon_emoji="⌨")  # keyboard emoji

        self._hotkey = QLineEdit()
        self._hotkey.setText(self._cfg.hotkey.combo)
        self._hotkey.setPlaceholderText("z.B. f8, ctrl+shift+space")
        self._hotkey.setToolTip(
            "Push-to-Talk-Hotkey (Format der `keyboard`-lib).\n"
            "Aenderung wirkt nach Kira-Neustart."
        )
        card.add_row("Diktat (PTT)", self._hotkey)

        # Edit-Command-Hotkey: F9 default, leer = Feature deaktiviert.
        self._edit_hotkey = QLineEdit()
        self._edit_hotkey.setText(self._cfg.hotkey.edit_combo or "")
        self._edit_hotkey.setPlaceholderText("z.B. f9 - leer = aus")
        self._edit_hotkey.setToolTip(
            "AI-Editing-Command-Hotkey: Text in der App selektieren,\n"
            "Hotkey halten, sprechen ('mach das foermlich' / 'uebersetz\n"
            "ins Englische'), loslassen. LLM ueberarbeitet die Selektion.\n"
            "Leer lassen, um das Feature zu deaktivieren."
        )
        card.add_row("Edit-Command", self._edit_hotkey)

        return card

    def _build_section_injector(self) -> _SectionCard:
        card = _SectionCard("Inject", icon_emoji="\U0001F4CB")  # clipboard emoji

        self._restore_ms = QSpinBox()
        self._restore_ms.setRange(100, 5000)
        self._restore_ms.setSingleStep(100)
        self._restore_ms.setSuffix(" ms")
        self._restore_ms.setValue(self._cfg.injector.restore_clipboard_after_ms)
        self._restore_ms.setToolTip(
            "Mindest-Wartezeit bevor das Clipboard wiederhergestellt wird.\n"
            "Lange Diktate skalieren automatisch (~2 ms pro Zeichen ab 80 chars)."
        )
        card.add_row("Clipboard-Restore", self._restore_ms)

        return card

    def _build_hint(self) -> QLabel:
        hint = QLabel(
            "<span style='color:#888;'>"
            "Änderungen wirken nach Kira-Neustart. Felder wie "
            "<code>whisper.model</code>, <code>initial_prompt</code> oder "
            "<code>context_modes</code> sind komplexer und werden über die "
            "Rohconfig bearbeitet."
            "</span>"
        )
        hint.setWordWrap(True)
        return hint

    def _build_raw_button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()
        raw_btn = QPushButton("Rohconfig öffnen…")
        raw_btn.setToolTip("Öffnet config.yaml in Notepad für komplexe Felder.")
        raw_btn.clicked.connect(self._open_raw)
        row.addWidget(raw_btn)
        return row

    def _build_button_box(self) -> QDialogButtonBox:
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        box.button(QDialogButtonBox.StandardButton.Save).setText("Speichern")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        return box

    # ----- handlers ------------------------------------------------------

    def _open_raw(self) -> None:
        self._cfg_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._cfg_path.exists():
            self._cfg_path.write_text(_MINIMAL_CONFIG, encoding="utf-8")
        subprocess.Popen(["notepad.exe", str(self._cfg_path)])

    def _save(self) -> None:
        # currentData() = userData des aktiven Items: None für Default,
        # sonst der Original-Device-Name (Substring-resilient gegen
        # PortAudio-Index-Shuffles nach USB-Hot-Plug).
        device_value = self._device.currentData()
        # Edit-Hotkey: leerer String -> None (Feature deaktiviert).
        edit_hotkey_value: str | None = self._edit_hotkey.text().strip() or None
        updates = {
            "audio.input_gain": float(self._gain.value()),
            "audio.input_device": device_value,
            "whisper.language": self._language.currentText(),
            "styler.model": self._styler_model.text().strip(),
            "styler.timeout_seconds": float(self._styler_timeout.value()),
            "injector.restore_clipboard_after_ms": int(self._restore_ms.value()),
            "hotkey.combo": self._hotkey.text().strip(),
            "hotkey.edit_combo": edit_hotkey_value,
        }

        self._cfg_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._cfg_path.exists():
            self._cfg_path.write_text(_MINIMAL_CONFIG, encoding="utf-8")

        try:
            current = self._cfg_path.read_text(encoding="utf-8")
            updated = update_scalars(current, updates)
            self._cfg_path.write_text(updated, encoding="utf-8")
        except KeyError as e:
            light_warning(
                self, "Kira",
                f"Config hat unbekanntes Schema ({e}).\n\n"
                "Bitte einmalig 'Rohconfig öffnen…' und sicherstellen, "
                "dass alle Sections (audio / whisper / styler / injector / "
                "hotkey) mit den Feldern existieren.",
            )
            return
        except Exception as e:
            log.exception("settings save failed")
            light_critical(self, "Kira", f"Speichern fehlgeschlagen: {e}")
            return

        light_information(
            self, "Kira",
            "Einstellungen gespeichert.\n\n"
            "Die meisten Änderungen wirken nach Kira-Neustart "
            "(Tray → Quit Kira, dann neu starten).",
        )
        self.accept()

    # ----- mic device picker ---------------------------------------------

    def _query_input_devices(self) -> list[tuple[int, str]]:
        """Return [(sd-index, name), …] für alle aktuellen Input-Devices.

        Tolerant gegen PortAudio-Race / Audio-Service-Disconnect — leere
        Liste bei Exception, der Default-Eintrag bleibt im Dropdown.
        Doppelte Namen (gleiche Kapsel via WASAPI/MME/DirectSound) werden
        bewusst alle gezeigt: der User wählt explizit die Host-API,
        Substring-Match in _resolve_device() trifft die erste passende.
        """
        try:
            import sounddevice as sd
            devices = list(sd.query_devices())
        except Exception:
            log.exception("sd.query_devices() failed in settings dialog")
            return []
        out: list[tuple[int, str]] = []
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0:
                name = d.get("name") or ""
                if name:
                    out.append((i, name))
        return out

    def _populate_device_combo(
        self, initial_value: int | str | None,
    ) -> None:
        """Combo füllen + Pre-Selection.

        initial_value kann None / int (alte Index-Configs) / str
        (Substring) sein. Beim Save speichern wir immer den Namen, damit
        alte int-Configs sich on-write zu robusten Substrings migrieren.
        """
        self._device.blockSignals(True)
        try:
            self._device.clear()
            self._device.addItem(_DEVICE_DEFAULT_LABEL, userData=None)
            devices = self._query_input_devices()
            for _idx, name in devices:
                self._device.addItem(name, userData=name)

            pos = self._match_initial(initial_value, devices)
            if pos is None:
                self._device.setCurrentIndex(0)
                if initial_value is None or not devices:
                    self._device_hint.setVisible(False)
                else:
                    self._device_hint.setText(
                        f"Bisher konfiguriert: '{initial_value}' - gerade "
                        "nicht erkannt. Mikro eingesteckt? 'Aktualisieren' "
                        "klicken. Sonst startet Kira mit dem Windows-Default."
                    )
                    self._device_hint.setVisible(True)
            else:
                self._device.setCurrentIndex(pos + 1)  # +1 für Default-Slot
                self._device_hint.setVisible(False)
        finally:
            self._device.blockSignals(False)

    @staticmethod
    def _match_initial(
        initial_value: int | str | None,
        devices: list[tuple[int, str]],
    ) -> int | None:
        """Position in `devices` (0-based) die zu initial_value passt, sonst None."""
        if initial_value is None or not devices:
            return None
        if isinstance(initial_value, int):
            for pos, (idx, _name) in enumerate(devices):
                if idx == initial_value:
                    return pos
            return None
        needle = str(initial_value).lower()
        if not needle:
            return None
        for pos, (_idx, name) in enumerate(devices):
            if needle in name.lower():
                return pos
        return None

    def _refresh_devices(self) -> None:
        """Re-query — behält die aktuelle Auswahl wenn sie noch existiert,
        sonst fällt auf Default + Hint zurück."""
        current = self._device.currentData()
        self._populate_device_combo(current)

    def _update_polish_model(self) -> None:
        model_name = self._styler_model.text().strip()
        if not model_name:
            light_warning(self, "Kira", "Bitte erst ein Polish-Modell eintragen.")
            return

        progress = QProgressDialog(
            f"Lade {model_name}…", "Abbrechen", 0, 0, self,
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setWindowTitle("Kira — Modell-Update")
        progress.setMinimumDuration(0)
        # QProgressDialog is a QDialog subclass — apply_light_theme flips
        # palette + QSS so the label/cancel button stay readable in
        # Win11 dark mode while the pull streams.
        apply_light_theme(progress)
        progress.show()

        thread = QThread(self)
        worker = _PullWorker(model_name)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def on_progress(status: str, completed: int, total: int) -> None:
            if total > 0:
                progress.setMaximum(total)
                progress.setValue(completed)
                pct = (completed / total) * 100
                mb_done = completed / (1024 * 1024)
                mb_total = total / (1024 * 1024)
                progress.setLabelText(
                    f"{status}\n{mb_done:.1f} / {mb_total:.1f} MB ({pct:.0f}%)"
                )
            else:
                progress.setLabelText(status or f"Lade {model_name}…")

        def on_finished(success: bool, message: str) -> None:
            progress.close()
            thread.quit()
            thread.wait()
            if success:
                light_information(self, "Kira", message)
            else:
                light_critical(self, "Kira", message)

        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        thread.start()
        # Keep refs alive until the worker finishes.
        self._pull_thread = thread
        self._pull_worker = worker
