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
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressDialog, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from kira.ui._dialog_style import (
    apply_light_theme,
    light_critical,
    light_information,
    light_warning,
)

from kira import __version__, UPDATE_REPO
from kira.config import default_config_path, effective_hotkey, load_config
from kira.config_writer import update_scalars

log = logging.getLogger(__name__)
from kira._resources import assets_dir as _assets_dir  # noqa: E402
_ASSETS = _assets_dir()

# userData-Sentinel für den "Windows-Default"-Combobox-Eintrag. Speichert
# beim _save() als input_device=None (= leerer String in der alten
# QLineEdit-Variante).
_DEVICE_DEFAULT_LABEL = "Windows-Default (automatisch)"

# Optionales unzensiertes Polish-LLM. Abliteriertes Qwen3.6 27B — die
# Inhaltsfilter des Modells sind entfernt. ~17 GB im Ollama-Cache, braucht
# ~16 GB VRAM beim Laden. Auf 16-GB-Karten passt es nicht neben Whisper
# (führt zu CPU-Offload und lahmem Polish), darum vor dem Pull ein
# GPU-Check. Wird per "Unzensiertes Modell laden…"-Button in der
# Polish-LLM-Card angeboten.
_UNCENSORED_MODEL = "huihui_ai/Qwen3.6-abliterated:27b"


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
        # Children und überschreibt z.B. QComboBox-Backgrounds.
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

    def add_widget(self, widget) -> None:
        """Add a full-width row ohne Label (z.B. für Status-Hinweise
        oder buttons die über die ganze Card-Breite gehen sollen)."""
        self._form.addRow(widget)


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


def _ollama_model_installed(model: str) -> bool:
    """Best-effort check ob ein Modell schon im lokalen Ollama-Cache liegt.

    Returns True wenn der Modellname (oder ein 'modellname:tag'-Match) in
    ollama.list() auftaucht. Bei API-Hick-Ups / Library-Fehlern: False —
    der Caller faellt dann auf ollama.pull() zurueck, was idempotent ist
    (kein Schaden ausser ein paar Sekunden Hash-Verify).
    """
    try:
        import ollama
        result = ollama.list()
        # API-Variation: result.models (neuere Versions, .model-Attribut)
        # vs. result['models'] (alte dict-Form, 'name'-Key).
        models = getattr(result, "models", None)
        if models is None and isinstance(result, dict):
            models = result.get("models", [])
        names: list[str] = []
        for m in (models or []):
            name = (
                getattr(m, "model", None)
                or getattr(m, "name", None)
                or (m.get("model") if isinstance(m, dict) else None)
                or (m.get("name") if isinstance(m, dict) else None)
                or ""
            )
            if name:
                names.append(str(name))
        if model in names:
            return True
        # Toleranz: "gemma3:4b" gegen "gemma3:4b-it-q4_K_M" als Substring-
        # Treffer durchlassen. Verhindert dass wir bei einem schon
        # vorhandenen Tag-Variant nochmal ziehen.
        return any(n.startswith(model) for n in names)
    except Exception:
        log.exception("ollama.list() failed during model-installed check")
        return False


# Adoptierte Pull-Worker-Threads, die nach Dialog-Close noch laufen.
# Wir halten Referenzen hier, damit der GC die QThread+QObject-Paare
# nicht einkassiert während run() im Hintergrund noch in ollama.pull()
# blockt — sonst Use-After-Free im Worker-Thread. Wird in
# SettingsDialog.closeEvent() befüllt, wenn ein Worker nach 3 s
# Cancel-Wait noch nicht beendet ist. Liste wird nie geleert — kosten
# ist vernachlässigbar (max. ein Eintrag pro Settings-Session) und der
# Cleanup beim Quit erledigt der Prozess-Tod ohnehin.
_orphan_pull_threads: list = []


# QProgressDialog.setMaximum/setValue nehmen C int32 (max 2_147_483_647 ≈ 2 GiB).
# Modell-Blobs sprengen das (unzensiertes Qwen3.6-27B: 17.4-GB-Blob) → OverflowError
# bei JEDEM Progress-Tick. Der v0.2.8-qint64-Fix korrigierte nur das _PullWorker-
# Signal; on_progress's setMaximum(int(total)) warf weiter (12651 Log-Einträge,
# "Endlosschleife" beim Modell-Pull). Auf eine feste 0..1000-Promille-Skala mappen;
# echte MB/Prozent kommen weiter aus den rohen Byte-Werten (Python-int, kein Overflow).
_PROGRESS_SCALE = 1000


def _progress_scale(completed: int, total: int) -> tuple[int, int]:
    """Mappt Byte-Werte auf ein int32-sicheres (maximum, value) für QProgressDialog.

    total<=0 → (0, 0) = unbestimmter Spinner (Größe noch unbekannt).
    completed wird auf [0, total] geclampt (ollama sendet beim Layer-Switch /
    in der Verifikationsphase gelegentlich completed>total).
    """
    if total <= 0:
        return (0, 0)
    safe = max(0, min(completed, total))
    return (_PROGRESS_SCALE, round(safe / total * _PROGRESS_SCALE))


class _PullWorker(QObject):
    """Background ollama.pull(model) — streams events back to the GUI.

    Signal-Typ ist `qint64` (nicht `int`) für completed/total. PyQt6
    marshalled `int` auf C `int` (32-bit signed) — sobald ein Modell-
    Layer > 2 GiB ist (z.B. das unzensierte Qwen3.6-27B mit mehreren
    GB-Layern), wrappt der Wert in den negativen Bereich und der User
    sieht Minusprozente im QProgressDialog.
    """
    progress = pyqtSignal(str, 'qint64', 'qint64')  # status, completed, total
    finished = pyqtSignal(bool, str)                # success, message

    def __init__(self, model_name: str) -> None:
        super().__init__()
        self._model = model_name
        self._cancelled = False

    def cancel(self) -> None:
        """Vom UI-Thread aufgerufen, wenn der User „Abbrechen" klickt
        oder den Dialog schließt. ollama.pull(stream=True) ist ein
        blocking Generator — wir können ihn nicht von außen unter-
        brechen. Stattdessen setzen wir ein Flag, das die Loop beim
        nächsten yield prüft und sauber aussteigt."""
        self._cancelled = True

    def run(self) -> None:
        try:
            import ollama
        except Exception as e:
            self.finished.emit(False, f"ollama-Library nicht verfügbar: {e}")
            return
        try:
            for event in ollama.pull(self._model, stream=True):
                if self._cancelled:
                    self.finished.emit(False, "Abgebrochen.")
                    return
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
            if self._cancelled:
                self.finished.emit(False, "Abgebrochen.")
                return
            self.finished.emit(True, f"{self._model} ist auf dem aktuellen Stand.")
        except Exception as e:
            log.exception("ollama.pull failed")
            self.finished.emit(False, f"Modell-Update fehlgeschlagen: {e}")


class _GpuCheckWorker(QObject):
    """Background GPU-VRAM-Check. nvidia-smi kann unter GPU-Last mehrere
    Sekunden brauchen — aktive CUDA-Kontexte (Whisper + Ollama auf der
    Karte) bremsen es aus. Der Check darf den Qt-Main-Thread daher nicht
    blockieren, sonst friert das Settings-Fenster ein."""
    finished = pyqtSignal(object)  # VramAssessment
    failed = pyqtSignal(str)

    def __init__(self, whisper_model: str, polish_model: str) -> None:
        super().__init__()
        self._whisper_model = whisper_model
        self._polish_model = polish_model

    def run(self) -> None:
        try:
            from kira.gpu_check import assess
            result = assess(
                whisper_model=self._whisper_model,
                polish_model=self._polish_model,
            )
            self.finished.emit(result)
        except Exception as exc:
            log.exception("GPU-Check fehlgeschlagen")
            self.failed.emit(str(exc))


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
  model: gemma4:12b
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
        self.setMinimumWidth(960)
        self.setModal(True)
        apply_light_theme(self)

        self._cfg = load_config()
        self._cfg_path = default_config_path()
        self._pull_thread: QThread | None = None
        self._pull_worker: _PullWorker | None = None
        self._gpu_thread: QThread | None = None
        self._gpu_worker: _GpuCheckWorker | None = None

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
        # Zwei-Spalten-Layout: links die Sprach-Pipeline (Audio,
        # Whisper, Polish-LLM), rechts Bedienung & Meta (Hotkeys,
        # Inject, Über Kira). Hält den Dialog kompakt (~780 statt
        # ~1270 px hoch). KEINE QScrollArea um die Cards — die bricht
        # unter Qt 6.11 die Theme-Vererbung, die Cards rendern dann
        # dunkel und der Label-Text wird unsichtbar (verifiziert
        # 2026-05-22, Repro Variant B vs C).
        host = QWidget()
        columns = QHBoxLayout(host)
        columns.setContentsMargins(0, 4, 0, 4)
        columns.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(self._build_section_audio())
        left.addWidget(self._build_section_whisper())
        left.addWidget(self._build_section_polish())
        left.addStretch()

        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(self._build_section_hotkeys())
        right.addWidget(self._build_section_injector())
        right.addWidget(self._build_section_about())
        right.addStretch()

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
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
            "selbst wenn der PortAudio-Index sich ändert.\n"
            "'Windows-Default' lässt Windows entscheiden - kann durch\n"
            "Noise-Cancel-Filter (ASUS, Nahimic) routen und Whisper-Quality killen."
        )
        mic_row.addWidget(self._device, 1)
        refresh_btn = QPushButton("Aktualisieren")
        refresh_btn.setToolTip(
            "Geraete neu abfragen - nutzen wenn ein Mikro eingesteckt wurde\n"
            "während dieser Dialog offen ist."
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
        self._styler_model.setPlaceholderText("z.B. gemma4:12b, gemma3:12b, qwen3:8b")
        polish_row.addWidget(self._styler_model)
        update_btn = QPushButton("Aktualisieren")
        update_btn.setToolTip(
            "Laedt das aktuelle Polish-Modell neu via ollama pull -\n"
            "z.B. nachdem die Ollama-Library eine neue Modell-Version\n"
            "veroeffentlicht hat."
        )
        update_btn.clicked.connect(self._update_polish_model)
        polish_row.addWidget(update_btn)
        card.add_row("Qualitätsmodell", polish_row)

        # Speed-Toggle: schaltet beim Polish gegen styler.fast_model
        # (Default gemma3:4b). Trade-off-Hinweis im Tooltip damit der User
        # versteht warum's das Toggle gibt — nicht jeder weiß dass 4b bei
        # F9-Editing und langen Briefings (>250 chars) leicht abfaellt.
        self._fast_mode = QCheckBox(
            f"Schneller Modus ({self._cfg.styler.fast_model})"
        )
        self._fast_mode.setChecked(self._cfg.styler.fast_mode)
        self._fast_mode.setToolTip(
            "Wenn aktiv, polished Kira mit dem schnellen Modell statt mit dem\n"
            "Qualitaetsmodell. Empfohlen wenn dein VRAM eng ist (Chrome,\n"
            "Outlook, RDP gleichzeitig offen) — sonst rutscht das 12B-Modell\n"
            "in den CPU-Offload und Polish dauert 2-4 s statt 0,3 s.\n\n"
            "Trade-offs:\n"
            "  • Polish (Punktuation, Großschreibung, Filler) praktisch identisch\n"
            "  • F9-Editing-Commands (Translate, Reformulate) merkbar schwaecher\n"
            "  • Lange Briefings (>250 chars) leicht inkonsistenter Stil\n\n"
            "Beim ersten Aktivieren wird das Modell ggf. heruntergeladen (~3 GB).\n"
            "Per-Mode-Overrides in styler.modes haben weiterhin Vorrang."
        )
        card.add_row("", self._fast_mode)

        self._styler_timeout = QDoubleSpinBox()
        self._styler_timeout.setRange(1.0, 120.0)
        self._styler_timeout.setSingleStep(1.0)
        self._styler_timeout.setDecimals(1)
        self._styler_timeout.setSuffix(" s")
        self._styler_timeout.setValue(self._cfg.styler.timeout_seconds)
        self._styler_timeout.setToolTip(
            "Timeout für den Polish-API-Call. 30 s ist robust für 12B-\n"
            "Modelle im Cold-Start; 5 s reicht für warm gehaltene 2B-Modelle."
        )
        card.add_row("Timeout", self._styler_timeout)

        # Optionales unzensiertes Modell: ein zusaetzlicher Button (kein
        # Umbau des _styler_model-Felds zu einer ComboBox) plus ein roter
        # Klartext-Hinweis darueber, was "unzensiert" bedeutet. Der rote
        # Hinweis ist ausdruecklich gewuenscht — sachlich, gut lesbar.
        uncensored_btn = QPushButton("Unzensiertes Modell laden…")
        uncensored_btn.setToolTip(
            "Laedt ein zusaetzliches, unzensiertes Polish-LLM "
            f"({_UNCENSORED_MODEL}, ~17 GB) via ollama pull und traegt es\n"
            "als Qualitaetsmodell ein. Vor dem Download laeuft ein GPU-Check —\n"
            "das 27B-Modell braucht ~16 GB VRAM und passt auf 16-GB-Karten\n"
            "nicht neben Whisper."
        )
        uncensored_btn.clicked.connect(self._offer_uncensored_model)
        card.add_row("", uncensored_btn)

        # 🔞-Badge groß + zentriert, darunter der Hinweis. Punktgröße 13
        # = Section-Card-Header-Emoji-Größe (s. _SectionCard.__init__).
        uncensored_badge = QLabel("🔞")
        _badge_font = QFont()
        _badge_font.setPointSize(13)
        uncensored_badge.setFont(_badge_font)
        uncensored_badge.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        card.add_widget(uncensored_badge)

        uncensored_hint = QLabel(
            "Unzensiert — die Inhaltsfilter des Modells sind entfernt. "
            "Es lehnt keine Eingaben ab und gibt ungefilterte Ausgaben zurück."
        )
        uncensored_hint.setStyleSheet(
            "color: #c0392b; font-size: 11px; font-weight: bold;"
        )
        uncensored_hint.setWordWrap(True)
        uncensored_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        card.add_widget(uncensored_hint)

        return card

    def _build_section_hotkeys(self) -> _SectionCard:
        card = _SectionCard("Hotkeys", icon_emoji="⌨")  # keyboard emoji

        self._hotkey = QLineEdit()
        self._hotkey.setText(effective_hotkey(self._cfg.hotkey.combo))
        self._hotkey.setPlaceholderText("z.B. f8, ctrl+shift+space")
        self._hotkey.setToolTip(
            "Push-to-Talk-Hotkey (Format der `keyboard`-lib).\n"
            "Änderung wirkt nach Kira-Neustart."
        )
        card.add_row("Diktat (PTT)", self._hotkey)

        # AI-Editing-Toggle: edit_combo=None deaktiviert den F9-Pfad
        # komplett. Die Checkbox ist der Master-Schalter, das Textfeld
        # darunter die Tastenwahl — bei abgeschalteter Checkbox ausgegraut.
        edit_enabled = self._cfg.hotkey.edit_combo is not None
        self._edit_enabled = QCheckBox("AI-Editing-Befehle aktiv")
        self._edit_enabled.setChecked(edit_enabled)
        self._edit_enabled.setToolTip(
            "Schaltet die AI-Editing-Befehle ganz ab oder an.\n"
            "Wenn aktiv: Text in der App markieren, den Hotkey halten,\n"
            "einen Befehl sprechen ('mach das förmlich' / 'übersetz ins\n"
            "Englische'), loslassen — das LLM überarbeitet die Markierung.\n"
            "Änderung wirkt nach Kira-Neustart."
        )
        self._edit_enabled.toggled.connect(self._on_edit_toggle)
        card.add_row("", self._edit_enabled)

        # Edit-Command-Hotkey: bei edit_combo=None mit "f9" vorbefüllt
        # (nur ausgegraut), damit das Feld beim Einschalten sofort einen
        # brauchbaren Wert hat.
        self._edit_hotkey = QLineEdit()
        self._edit_hotkey.setText(self._cfg.hotkey.edit_combo or "f9")
        self._edit_hotkey.setPlaceholderText("z.B. f9")
        self._edit_hotkey.setEnabled(edit_enabled)
        self._edit_hotkey.setToolTip(
            "Welche Taste die AI-Editing-Befehle auslöst (Standard: f9).\n"
            "Nur aktiv, wenn die Checkbox oben gesetzt ist."
        )
        card.add_row("Edit-Command", self._edit_hotkey)

        return card

    def _on_edit_toggle(self, checked: bool) -> None:
        """AI-Editing-Checkbox umgeschaltet: Hotkey-Feld aus-/eingrauen.
        Beim Einschalten ein leeres Feld mit dem Default 'f9' füllen,
        damit der Toggle sofort einen gültigen Hotkey hat."""
        self._edit_hotkey.setEnabled(checked)
        if checked and not self._edit_hotkey.text().strip():
            self._edit_hotkey.setText("f9")

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

    def _build_section_about(self) -> _SectionCard:
        card = _SectionCard("Über Kira", icon_emoji="ℹ")  # info emoji

        version_lbl = QLabel(f"Version {__version__}")
        version_lbl.setStyleSheet("color: #555; font-size: 11px;")
        card.add_row("Version", version_lbl)

        repo_lbl = QLabel(
            f"<a href='https://github.com/{UPDATE_REPO}' "
            f"style='color: #4a76b8; text-decoration: none;'>"
            f"github.com/{UPDATE_REPO}</a>"
        )
        repo_lbl.setOpenExternalLinks(True)
        repo_lbl.setStyleSheet("font-size: 11px;")
        card.add_row("Quelle", repo_lbl)

        # Drei Buttons rechts in einer Row: Anleitung / GPU prüfen /
        # Updates suchen. Anleitung öffnet WelcomeDialog im as_help-Modus.
        # GPU-Check schaetzt VRAM-Bedarf von aktuellem Whisper + Polish
        # gegen die installierte Karte. Update-Button: Multi-Asset-Bundle-
        # Pull mit SHA256-Verify; Auto-Quit nach Setup-Launch.
        button_row = QHBoxLayout()
        button_row.addStretch()
        help_btn = QPushButton("Anleitung...")
        help_btn.setToolTip(
            "Volle Bedienungsanleitung: Diktat, Edit-Commands, File-\n"
            "Transkription, Modi und Updates."
        )
        help_btn.clicked.connect(self._open_help_from_settings)
        button_row.addWidget(help_btn)
        gpu_btn = QPushButton("GPU prüfen")
        gpu_btn.setToolTip(
            "Prüf ob die installierte GPU genug VRAM hat für Whisper\n"
            "+ aktuelles Polish-LLM. Zeigt Karten-Name, VRAM-Total,\n"
            "geschaetzten Bedarf und Headroom-Reserve."
        )
        gpu_btn.clicked.connect(self._run_gpu_check)
        button_row.addWidget(gpu_btn)
        update_btn = QPushButton("Updates suchen...")
        update_btn.setToolTip(
            "Holt die neueste Version von github.com/MikeGT4/kira,\n"
            "verifiziert SHA256-Hashes (falls vorhanden) und startet\n"
            "den Setup-Wizard. Kira beendet sich dafür kurz."
        )
        update_btn.clicked.connect(self._run_update_check)
        button_row.addWidget(update_btn)
        card.add_widget(self._wrap_layout_in_widget(button_row))

        return card

    @staticmethod
    def _wrap_layout_in_widget(layout) -> QWidget:
        """QFormLayout.addRow erwartet QWidget oder einen QLayout-Wrapper —
        die direkte Form mit QHBoxLayout funktioniert über addRow(widget),
        also wickeln wir's in einen leeren QWidget."""
        wrapper = QWidget()
        wrapper.setLayout(layout)
        return wrapper

    @staticmethod
    def _resolve_edit_combo(enabled: bool, text: str) -> str | None:
        """Checkbox-Zustand + Hotkey-Feld → Wert für hotkey.edit_combo.

        Checkbox aus → None (Feature deaktiviert). Checkbox an → der
        getrimmte Feldwert, oder None wenn das Feld leer ist. Reine
        Funktion, damit die einzige Verhaltenslogik des F9-Toggles ohne
        QApplication testbar bleibt (siehe tests/test_settings_dialog.py)."""
        if not enabled:
            return None
        return text.strip() or None

    @staticmethod
    def _uncensored_gpu_blocks(status: str) -> bool:
        """GPU-Check-Status → muss vor dem 27B-Pull eine Warnung mit
        Abbruch-Option gezeigt werden?

        'insufficient'/'tight' → True (zu wenig bzw. knapper VRAM für ein
        ~16-GB-Modell neben Whisper). 'ok'/'no_gpu' → False: 'ok' ist
        unkritisch, 'no_gpu' bedeutet keine NVIDIA-Karte — dafür hat der
        GPU-Check-Button schon einen eigenen Hinweis, hier nicht doppelt
        nerven. Reine Funktion, damit die Entscheidungslogik des
        Uncensored-Buttons ohne QApplication testbar bleibt (siehe
        tests/test_settings_dialog.py)."""
        return status in ("insufficient", "tight")

    def _run_update_check(self) -> None:
        """Update-Flow aus dem Settings-Dialog. Auto-Quit-Callback ruft
        QApplication.quit() — umgeht den Tray-Cleanup, aber praktikabel
        weil Inno's Setup eh auf Mutex-Release wartet."""
        from PyQt6.QtCore import QCoreApplication
        from kira.ui._update_runner import run_update_flow

        def request_quit() -> None:
            inst = QCoreApplication.instance()
            if inst is not None:
                inst.quit()

        run_update_flow(parent=self, on_quit_request=request_quit)

    def _open_help_from_settings(self) -> None:
        """Öffnet WelcomeDialog im as_help=True-Modus aus dem Settings-
        Dialog. Modal auf den Settings-Dialog (nicht globaler App), damit
        der User nach dem Lesen genau zum vorigen Konfig-Punkt zurückkehrt."""
        from kira.ui.welcome_dialog import WelcomeDialog
        dlg = WelcomeDialog(as_help=True)
        dlg.setParent(self, dlg.windowFlags())
        getattr(dlg, "exec")()

    def _run_gpu_check(self) -> None:
        """Schaetzt VRAM-Bedarf von aktuellem Whisper + Polish-Modell gegen
        die installierte Karte. Status (ok/tight/insufficient/no_gpu)
        bestimmt Dialog-Severity (info/warning/critical/warning).

        Whisper-Model + Polish-Model werden aus den AKTUELLEN Form-Werten
        gelesen (nicht vom geladenen self._cfg) — so kann der User in der
        Settings-UI ein anderes Polish-Modell tippen und sofort den Check
        gegen DAS Modell laufen lassen.

        Laeuft auf einem QThread: nvidia-smi kann unter GPU-Last mehrere
        Sekunden brauchen (aktive CUDA-Kontexte von Whisper + Ollama).
        Synchron im Main-Thread wuerde der Aufruf das Settings-Fenster
        einfrieren — genau dieser zu knappe Timeout liess detect_gpu
        frueher faelschlich 'keine GPU' melden. Ein GpuScanDialog
        (Oszilloskop-Look) zeigt waehrenddessen eine animierte
        Neon-Welle statt eines statischen Hinweises."""
        polish_text = self._styler_model.text().strip() or self._cfg.styler.model
        whisper_model = self._cfg.whisper.model
        title = "Kira — GPU-Check"

        from kira.ui._gpu_scan_dialog import GpuScanDialog
        scan = GpuScanDialog(self)
        scan.start()

        thread = QThread(self)
        worker = _GpuCheckWorker(whisper_model, polish_text)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def on_finished(result) -> None:
            scan.finish()
            thread.quit()
            thread.wait()
            if result.status == "ok":
                light_information(self, title, result.message)
            elif result.status == "tight":
                light_warning(self, title, result.message)
            elif result.status == "insufficient":
                light_critical(self, title, result.message)
            else:  # no_gpu
                light_warning(self, title, result.message)

        def on_failed(message: str) -> None:
            scan.finish()
            thread.quit()
            thread.wait()
            light_critical(
                self, title, f"GPU-Check fehlgeschlagen:\n\n{message}",
            )

        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        thread.start()
        # Refs halten bis der Worker fertig ist (sonst GC-Risiko).
        self._gpu_thread = thread
        self._gpu_worker = worker

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
        try:
            subprocess.Popen(["notepad.exe", str(self._cfg_path)])
        except (OSError, FileNotFoundError) as exc:
            # Win11 N-Edition / Kiosk / Corporate Policy kann notepad
            # entfernen — silent-failure-hunt 2026-05-09. Stattdessen
            # User informieren + Pfad anzeigen damit er manuell oeffnen
            # kann.
            log.exception("notepad launch failed for %s", self._cfg_path)
            light_warning(
                self, "Kira",
                f"Notepad konnte nicht gestartet werden: {exc}\n\n"
                f"Öffne die Datei manuell:\n{self._cfg_path}",
            )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Beim Dialog-Close den ggf. laufenden Polish-Pull-Worker
        sauber beenden — sonst feuert das thread-Worker-Signal an einen
        bereits zerstoerten Dialog (Segfault unter Qt6). best-practice
        2026-05-09.

        Aktualisiert 2026-05-28: KEIN thread.terminate() mehr. Die
        Qt-Doku markiert QThread::terminate() explizit als unsafe —
        es kann Mutexe halten oder den Heap inkonsistent lassen und
        den ganzen Prozess crashen. Symptom bei Mike: „Programm hängt
        sich auf", weil der Worker im socket.recv() auf das nächste
        ollama-Stream-Event wartete (langer Layer-Download) und nach
        3 s Timeout terminate() den Tray-Prozess mit-ins-Grab nahm.

        Neue Strategie: cancel flag setzen, UI-Signals trennen (damit
        spätere emit()s nicht in zerstörte Widgets schreiben), kurz
        warten, und falls der Worker hängt: Thread+Worker in eine
        Modul-Level-Liste „adoptieren" lassen, damit GC sie nicht
        einkassiert während run() noch läuft. Wenn ollama.pull
        irgendwann doch returnt (Netz wieder da / Pull fertig),
        beendet sich der Worker dann sauber von selbst."""
        thread = self._pull_thread
        worker = self._pull_worker
        if worker is not None:
            worker.cancel()
        if thread is not None and thread.isRunning():
            if worker is not None:
                # Nach Disconnect kommen keine Updates mehr durch —
                # selbst wenn der Worker noch lebt und emittiert, fängt
                # ihn niemand mehr auf einem zerstörten Dialog ab.
                try:
                    worker.progress.disconnect()
                except (TypeError, RuntimeError):
                    pass
                try:
                    worker.finished.disconnect()
                except (TypeError, RuntimeError):
                    pass
            log.info(
                "Settings dialog closing while polish-pull running — "
                "cancel flagged, waiting up to 3s for clean exit",
            )
            thread.quit()
            if not thread.wait(3000):
                log.warning(
                    "polish-pull thread did not exit in 3s; orphaning "
                    "(no terminate — would risk process-wide crash)",
                )
                _orphan_pull_threads.append((thread, worker))
        super().closeEvent(event)

    def _save(self) -> None:
        # currentData() = userData des aktiven Items: None für Default,
        # sonst der Original-Device-Name (Substring-resilient gegen
        # PortAudio-Index-Shuffles nach USB-Hot-Plug).
        device_value = self._device.currentData()
        # AI-Editing: Checkbox aus → edit_combo=None. Checkbox an mit
        # leerem Feld ist widersprüchlich — der User soll es korrigieren,
        # statt still in ein deaktiviertes Feature zu laufen.
        edit_enabled = self._edit_enabled.isChecked()
        if edit_enabled and not self._edit_hotkey.text().strip():
            light_warning(
                self, "Kira",
                "Bitte einen Hotkey für die AI-Editing-Befehle eintragen "
                "oder das Häkchen bei „AI-Editing-Befehle aktiv“ entfernen.",
            )
            return
        edit_hotkey_value = self._resolve_edit_combo(
            edit_enabled, self._edit_hotkey.text(),
        )
        new_fast_mode = self._fast_mode.isChecked()

        # Speed-Toggle eingeschaltet aber fast_model nicht installiert?
        # → erst ollama pull mit Progress-Dialog, sonst kommt der User
        # nach Restart in ein leises Polish-Failure (fallback_to_raw
        # greift, aber er weiss nicht warum sein Toggle nichts bewirkt).
        # Pre-Check NUR bei Neu-Aktivierung — wenn der Toggle eh schon an
        # war (nur andere Felder geaendert), schenken wir uns den Pull.
        if new_fast_mode and not self._cfg.styler.fast_mode:
            fast_model = self._cfg.styler.fast_model
            if not _ollama_model_installed(fast_model):
                if not self._pull_blocking(fast_model):
                    # User hat abgebrochen oder Pull failed -> Save
                    # abbrechen, Toggle zurueck auf alten Stand
                    self._fast_mode.setChecked(False)
                    return

        updates = {
            "audio.input_gain": float(self._gain.value()),
            "audio.input_device": device_value,
            "whisper.language": self._language.currentText(),
            "styler.model": self._styler_model.text().strip(),
            "styler.fast_mode": new_fast_mode,
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
        self._start_model_pull(model_name, "Kira — Modell-Update")

    def _start_model_pull(
        self,
        model_name: str,
        window_title: str,
        on_success=None,
        on_done=None,
    ) -> None:
        """Gemeinsamer Modell-Pull mit QProgressDialog + QThread + _PullWorker.

        Genutzt von `_update_polish_model` (Polish-Modell aktualisieren)
        und `_offer_uncensored_model` (unzensiertes Modell laden) — die
        Pull-Mechanik ist identisch, nur der Erfolgs-Folgeschritt
        unterscheidet sich. `on_success`, falls gesetzt, wird nach einem
        erfolgreichen Pull statt der Standard-light_information aufgerufen
        (z.B. um das Modell als Qualitaetsmodell einzutragen).

        `on_done(success: bool)` wird IMMER aufgerufen, wenn der Pull
        finisht (success oder fail/abgebrochen) — vom blocking Save-
        Path benutzt, der das Ergebnis abwarten und in eine QEventLoop
        weiterleiten muss."""
        progress = QProgressDialog(
            f"Lade {model_name}…", "Abbrechen", 0, 0, self,
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setWindowTitle(window_title)
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
            # Defense-in-depth: ollama-Stream kann beim Layer-Switch
            # oder in der Verifikations-Phase completed > total senden.
            # Ohne Clamp landet setValue() über setMaximum() und Qt
            # zeigt eine Endlos-Animation statt der echten Prozent.
            if total > 0:
                safe_completed = max(0, min(completed, total))
                maximum, value = _progress_scale(completed, total)
                progress.setMaximum(maximum)
                progress.setValue(value)
                pct = (safe_completed / total) * 100
                mb_done = safe_completed / (1024 * 1024)
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
                if on_success is not None:
                    on_success()
                else:
                    light_information(self, "Kira", message)
            else:
                # Vom User abgebrochene Pulls sind kein Fehler — nur
                # echte Fail-Cases (Ollama down, Netz weg, Modell-Name
                # falsch) verdienen das rote Critical-Dialog.
                if message != "Abgebrochen.":
                    light_critical(self, "Kira", message)
            if on_done is not None:
                on_done(success)

        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        # Cancel-Button im QProgressDialog flaggt den Worker. Der
        # Generator-Loop checkt das Flag beim nächsten yield und
        # steigt mit finished.emit(False, "Abgebrochen.") aus —
        # ohne diese Verdrahtung hatte der Abbrechen-Knopf keinerlei
        # Wirkung und der User saß stundenlang vor einem laufenden
        # 27-GB-Download fest.
        progress.canceled.connect(worker.cancel)
        thread.start()
        # Keep refs alive until the worker finishes.
        self._pull_thread = thread
        self._pull_worker = worker

    def _pull_blocking(self, model_name: str) -> bool:
        """Synchroner Modell-Pull mit Progress-Dialog — blockt bis fertig.

        Vom Save-Pfad benutzt: wenn der User „Schneller Modus"
        aktiviert und das fast_model fehlt, muss es VOR dem Speichern
        da sein — sonst polished Kira nach Restart in einen leeren
        Fallback (raw Whisper) ohne dass der User die Ursache sieht.

        Verschachtelt _start_model_pull mit einer lokalen QEventLoop,
        die im on_done-Callback quittiert wird. So bleibt die Pull-
        Mechanik (QProgressDialog, qint64-Signale, Cancel-Wiring,
        Orphan-Cleanup) zentral an einer Stelle und die blocking
        Variante teilt sich alle Bug-Fixes mit der Fire-and-Forget-
        Variante.
        """
        from PyQt6.QtCore import QEventLoop
        loop = QEventLoop()
        state = {"success": False}

        def on_pull_done(success: bool) -> None:
            state["success"] = success
            loop.quit()

        self._start_model_pull(
            model_name,
            "Kira — Modell wird geladen",
            on_done=on_pull_done,
        )
        loop.exec()
        return state["success"]

    def _offer_uncensored_model(self) -> None:
        """Bietet das optionale unzensierte Polish-LLM an: GPU-Check,
        dann Pull, dann als Qualitaetsmodell eintragen.

        Ablauf:
          1. gpu_check.assess() gegen das 27B-Modell. Bei knappem/zu
             wenig VRAM eine Warnung mit Ja/Nein — der User kann
             abbrechen (CPU-Offload macht Polish unbrauchbar lahm).
          2. Wenn das Modell schon im Ollama-Cache liegt: Pull
             ueberspringen, direkt eintragen.
          3. Sonst: Pull via gemeinsamem _start_model_pull-Helper.
          4. Nach Erfolg: ins _styler_model-Feld eintragen + Hinweis,
             dass mit 'Speichern' bestaetigt werden muss.
        """
        from kira.gpu_check import assess

        result = assess(
            whisper_model=self._cfg.whisper.model,
            polish_model=_UNCENSORED_MODEL,
        )
        if self._uncensored_gpu_blocks(result.status):
            severity = (
                QMessageBox.Icon.Critical
                if result.status == "insufficient"
                else QMessageBox.Icon.Warning
            )
            box = QMessageBox(self)
            box.setIcon(severity)
            box.setWindowTitle("Kira — Unzensiertes Modell")
            box.setText(
                f"{result.message}\n\n"
                f"Das unzensierte Modell ({_UNCENSORED_MODEL}) braucht "
                "~16 GB VRAM. Reicht der VRAM nicht, lagert Ollama Teile "
                "auf die CPU aus und der Polish-Schritt wird deutlich "
                "langsamer (mehrere Sekunden statt Sekundenbruchteilen).\n\n"
                "Trotzdem herunterladen?"
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            box.setDefaultButton(QMessageBox.StandardButton.No)
            yes = box.button(QMessageBox.StandardButton.Yes)
            if yes is not None:
                yes.setText("Trotzdem laden")
            no = box.button(QMessageBox.StandardButton.No)
            if no is not None:
                no.setText("Abbrechen")
            apply_light_theme(box)
            if box.exec() != QMessageBox.StandardButton.Yes.value:
                return

        if _ollama_model_installed(_UNCENSORED_MODEL):
            # Schon lokal vorhanden — Pull ueberspringen, direkt eintragen.
            self._apply_uncensored_model()
            return

        self._start_model_pull(
            _UNCENSORED_MODEL,
            "Kira — Unzensiertes Modell",
            on_success=self._apply_uncensored_model,
        )

    def _apply_uncensored_model(self) -> None:
        """Traegt das unzensierte Modell als Qualitaetsmodell ein und
        informiert den User. Weist auf die fast_mode-Falle hin: bei
        aktivem 'Schneller Modus' polished Kira gegen styler.fast_model —
        das hier eingetragene 27B-Modell haette dann keinen Effekt."""
        self._styler_model.setText(_UNCENSORED_MODEL)
        message = (
            "Das unzensierte Modell ist bereit und wurde als "
            f"Qualitaetsmodell eingetragen ({_UNCENSORED_MODEL}).\n\n"
            "Klick auf 'Speichern', damit die Aenderung uebernommen wird."
        )
        if self._fast_mode.isChecked():
            message += (
                "\n\nHinweis: Der 'Schnelle Modus' ist aktiv. Solange er "
                "eingeschaltet ist, polished Kira mit dem schnellen Modell "
                f"({self._cfg.styler.fast_model}) — das unzensierte "
                "Qualitaetsmodell hat dann keinen Effekt. Schalte den "
                "Schnellen Modus aus, wenn das unzensierte Modell genutzt "
                "werden soll."
            )
        light_information(self, "Kira", message)
