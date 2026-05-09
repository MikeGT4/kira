"""First-run welcome dialog AND on-demand "Anleitung" via Tray-Menue.

Ein Dialog, zwei Modi:

- as_help=False (default): Welcome-Modus. Wird beim ersten Start gezeigt
  wenn die installierte Version größer ist als die im Marker
  vermerkte. Mit "Loslegen"-Button + "Bei diesem Update nicht mehr
  zeigen"-Checkbox (default ticked).

- as_help=True: Help-Modus. Aus dem Tray-Menue ("Anleitung...") oder
  dem Hilfe-Button im Settings-Dialog aufgerufen. Title = "Anleitung",
  kein Checkbox/Marker-Write, nur "Schließen"-Button.

Versions-aware Marker (seit v0.2): %APPDATA%\\Kira\\.welcomed enthaelt
die Version-Number, die der User zuletzt durchgewinkt hat. Bei jedem
Boot vergleichen wir vs __version__ — wenn die installierte Version
größer ist (User hat upgegradet), zeigen wir den Dialog erneut
("Was ist neu in vX.Y.Z?"). Old-style Marker (Inhalt "welcomed" aus
v0.1.0) faellt unter "kann nicht geparst werden" und triggert den
Dialog ein letztes Mal — danach steht die Version drin.
"""
from __future__ import annotations
import logging
import os
from pathlib import Path

from packaging.version import InvalidVersion, parse as parse_version
from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout,
)

from kira import __version__

log = logging.getLogger(__name__)
_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
_WELCOME_MARKER = Path(os.environ.get("APPDATA", str(Path.home()))) / "Kira" / ".welcomed"


def _load_branded_pixmap(size: int) -> QPixmap | None:
    """Largest-frame ICO loader (Pillow → QPixmap). QPixmap's nativer
    ICO-Loader nimmt eine willkuerlich kleine Frame und upscalet —
    bleibt bei größeren Sizes blurry. Pillow lässt uns die 256-Frame
    explizit wählen + einmal mit LANCZOS runterskalieren."""
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
        log.exception("failed to load icon-branded.ico")
        return None


def is_first_run() -> bool:
    """True wenn der User die aktuelle Version noch nicht durchgewinkt hat.

    - Marker fehlt → True (echter erster Start)
    - Marker existiert mit gültiger Version >= __version__ → False
    - Marker existiert mit gültiger Version < __version__ → True (Upgrade)
    - Marker existiert mit ungültiger Version (v0.1-Stil "welcomed") → True
      (einmalig zeigen, beim Accept wird die Version geschrieben)
    """
    if not _WELCOME_MARKER.exists():
        return True
    try:
        marker_text = _WELCOME_MARKER.read_text(encoding="utf-8").strip()
    except OSError as exc:
        log.warning("welcome marker unreadable: %s — showing dialog", exc)
        return True
    try:
        marker_version = parse_version(marker_text)
        current_version = parse_version(__version__)
    except InvalidVersion:
        log.info(
            "welcome marker holds non-version text %r (v0.1-Stil?) — "
            "showing once, will upgrade to %s on accept",
            marker_text, __version__,
        )
        return True
    return marker_version < current_version


def mark_welcomed() -> None:
    """Schreibe die aktuelle Version in den Marker. Beim nächsten Boot
    mit derselben Version wird is_first_run False; nach Major/Minor-Bump
    zeigt sich der Dialog wieder ('Was ist neu')."""
    _WELCOME_MARKER.parent.mkdir(parents=True, exist_ok=True)
    _WELCOME_MARKER.write_text(__version__, encoding="utf-8")


_GUIDE_HTML = """
<p>Kira ist dein lokaler Sprache-zu-Text-Helfer. Alles läuft auf deinem PC —
keine Cloud, keine Telemetrie. Whisper transkribiert, ein lokales LLM (Ollama)
poliert.</p>

<h3>1. Diktieren (Push-to-Talk)</h3>
<ul>
  <li>Halte <b>F8</b> in jedem beliebigen Programm.</li>
  <li>Sprich, was du tippen willst.</li>
  <li>Lass F8 los — der polierte Text erscheint dort, wo dein Cursor steht.</li>
</ul>
<p style='color:#666; font-size:11px;'>Mindestens ~300 ms halten, sonst wird
die Aufnahme als Aus-Versehen-Tap gewertet.</p>

<h3>2. AI-Editing-Commands (Selektion überarbeiten)</h3>
<ul>
  <li>Markiere Text in einer beliebigen App.</li>
  <li>Halte <b>F9</b> und sage einen Befehl:
    „mach das förmlich" / „übersetz auf Englisch" /
    „fass das in 3 Bullets zusammen".</li>
  <li>Lass F9 los — die Selektion wird durch den überarbeiteten Text ersetzt.</li>
</ul>
<p style='color:#666; font-size:11px;'>F9 nutzt Strg+C im Hintergrund.
Wenn nichts selektiert ist, ist der Hotkey ein No-Op.</p>

<h3>3. Datei transkribieren</h3>
<p>Tray-Icon (rechts unten) → Rechtsklick → <b>„Datei transkribieren..."</b>.
Audio (.wav, .mp3, .m4a, .flac, .ogg, .opus) oder Video
(.mp4, .mov, .mkv, .webm) auswählen — Kira speichert die Transkription
als <code>.txt</code> neben der Eingabedatei.</p>

<h3>4. Modi &amp; Custom Dictionary</h3>
<p>Kira erkennt automatisch in welcher App du tippst (Outlook → förmliche
Email, Slack → lockerer Chat, VS Code → Code) und nutzt unterschiedliche
Polish-Prompts. Eingebaute Modi:
<code>email</code>, <code>chat</code>, <code>code</code>,
<code>terminal</code>, <code>plain</code>, <code>clean</code>
(Filler-Filter only),
<code>translate_en</code> (Deutsch→Englisch),
<code>email_formal</code> (Sie-Form, Praxis-Stil).</p>
<p>Eigennamen, Markennamen und Fachbegriffe werden oft falsch transkribiert
(„what's app" statt „WhatsApp", „chat g pt" statt „ChatGPT",
„java skript" statt „JavaScript"). In Settings →
„Rohconfig öffnen..." kannst du eine Replacement-Map setzen, die
Whisper-Output VOR dem Polish korrigiert:</p>
<pre style='background:#f4f4f4; color:#1d1d1f; padding:8px; border-radius:4px; font-size:10px;'>
whisper:
  replacements:
    "what's app": "WhatsApp"
    "chat g pt": "ChatGPT"
    "java skript": "JavaScript"
</pre>

<h3>5. Updates</h3>
<p>Tray → <b>„Updates suchen..."</b> oder Settings → „Über Kira" → Update-Button.
Kira prüft GitHub Releases, lädt das Multi-Asset-Bundle (Stub + Splits),
verifiziert SHA256-Hashes (falls im Release vorhanden), und startet den
Setup-Wizard. Kira beendet sich dafür kurz.</p>

<h3>6. Tray &amp; Status</h3>
<p>Das Tray-Icon zeigt den Zustand:</p>
<ul>
  <li><b>Grau</b>: bereit (Idle)</li>
  <li><b>Rot</b>: aufnehmen (Recording)</li>
  <li><b>Blau</b>: transkribieren oder polieren</li>
  <li><b>Gelb</b>: Fehler — siehe „Open Log..."</li>
</ul>

<h3>Konfiguration</h3>
<p>Tray → <b>„Einstellungen..."</b>: Mic-Gain, Mikrofon-Auswahl,
Whisper-Sprache, Polish-Modell, Hotkeys (F8 + F9), Clipboard-Restore-Delay.
Komplexe Felder (Replacements, Modi, Initial-Prompt) über „Rohconfig öffnen...".</p>

<h3>Logs</h3>
<p>Tray → <b>„Open Log..."</b>: <code>%LOCALAPPDATA%\\Kira\\kira.log</code>.
Bei nativen Crashes: <code>kira-faulthandler.log</code> daneben.</p>
"""


class WelcomeDialog(QDialog):
    """Welcome-Modus oder Help-Modus, je nach as_help-Parameter."""

    def __init__(self, as_help: bool = False) -> None:
        super().__init__()
        self._as_help = as_help

        if as_help:
            self.setWindowTitle("Kira - Anleitung")
            heading_text = "Kira - Anleitung"
            cta_text = "Schließen"
        else:
            self.setWindowTitle("Willkommen bei Kira")
            heading_text = "Willkommen bei Kira"
            cta_text = "Loslegen"

        icon_path = _ASSETS / "icon-branded.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(640, 640)
        self.resize(680, 760)
        self.setModal(True)
        from kira.ui._dialog_style import apply_light_theme
        apply_light_theme(self)

        # Apple-Look-Overrides als ANHANG an das Light-Theme-Stylesheet,
        # NICHT als Ersatz. apply_light_theme ruft setStyleSheet(_QSS) —
        # wenn wir hier mit reinem self.setStyleSheet("Apple-only...")
        # überschreiben, verlieren wir die _QSS-Regeln (QLabel-color #222,
        # QPushButton-Restyle gegen Win11-Fluent's transparenten Default,
        # QComboBox-Theme). Resultat war: Win11-Dark-Palette schlug bei
        # Heading + Body wieder durch, weisses pre-Block hatte hell-Text-
        # default → hell-on-hell unleserlich. Mike's Bug-Report 2026-05-09.
        self.setObjectName("welcomeDialog")
        apple_extensions = (
            "QDialog#welcomeDialog { background: #ffffff; }"
            "QDialog#welcomeDialog QPushButton[primary='true'] {"
            "  background: #007AFF;"
            "  color: white;"
            "  border: none;"
            "  border-radius: 8px;"
            "  padding: 9px 22px;"
            "  font-size: 13px;"
            "  font-weight: 500;"
            "  min-width: 100px;"
            "}"
            "QDialog#welcomeDialog QPushButton[primary='true']:hover {"
            "  background: #0062cc;"
            "}"
            "QDialog#welcomeDialog QPushButton[primary='true']:pressed {"
            "  background: #004da3;"
            "}"
            "QDialog#welcomeDialog QCheckBox {"
            "  color: #555;"
            "  font-size: 11px;"
            "  background: transparent;"
            "}"
        )
        self.setStyleSheet(self.styleSheet() + apple_extensions)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 24)
        layout.setSpacing(14)

        # Brand-Hierarchie: digitalroots oben (kleiner, dezent — Hersteller-
        # Wordmark), Kira-Glyph DARUNTER prominent (App-Identitaet, was der
        # User wiedererkennen soll). Mike-Vorgabe 2026-05-09.
        dr_label = QLabel()
        dr_path = _ASSETS / "digitalroots-logo.png"
        if dr_path.exists():
            dr_pix = QPixmap(str(dr_path)).scaledToWidth(
                240, Qt.TransformationMode.SmoothTransformation,
            )
            dr_label.setPixmap(dr_pix)
        dr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dr_label)

        kira_label = QLabel()
        kira_pix = _load_branded_pixmap(96)
        if kira_pix is not None:
            kira_label.setPixmap(kira_pix)
        kira_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kira_label.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(kira_label)

        heading = QLabel(heading_text)
        heading_font = QFont()
        heading_font.setPointSize(22)
        heading_font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(heading_font)
        heading.setStyleSheet("color: #1d1d1f;")  # Apple-System-Black
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        # Scrollbarer Body — der Inhalt ist umfangreicher als 540 px sind und
        # waechst mit jeder Feature-Welle. ScrollArea statt FixedHeight damit
        # auch auf 1080p alles sichtbar ist.
        body_widget = QLabel(_GUIDE_HTML)
        body_widget.setWordWrap(True)
        body_widget.setTextFormat(Qt.TextFormat.RichText)
        body_widget.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        body_widget.setAlignment(Qt.AlignmentFlag.AlignTop)
        body_font = QFont()
        body_font.setPointSize(10)
        body_widget.setFont(body_font)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body_widget)
        # Scrollbar IMMER zeigen — Default ist AsNeeded, aber der Win11-
        # Default-Scrollbar ist hellgrau auf hellem Card-BG quasi
        # unsichtbar. AlwaysOn + explicit QScrollBar-Stylesheet macht
        # ihn klar erkennbar (12 px breit, dunkler Handle).
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn,
        )
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QLabel { padding: 0 4px; }"
            "QScrollBar:vertical {"
            "  background: #f0f0f0;"
            "  width: 12px;"
            "  margin: 0;"
            "  border: 1px solid #d8d8d8;"
            "  border-radius: 6px;"
            "}"
            "QScrollBar::handle:vertical {"
            "  background: #b0b0b0;"
            "  min-height: 30px;"
            "  border-radius: 5px;"
            "}"
            "QScrollBar::handle:vertical:hover {"
            "  background: #909090;"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            "  height: 0;"
            "}"
        )
        layout.addWidget(scroll, stretch=1)

        # Checkbox nur im Welcome-Modus — im Help-Modus waere "nicht mehr
        # zeigen" sinnfrei (er wird ja nur on-demand geöffnet).
        # Text-Fassung passt zur version-aware Marker-Logik: wenn der User
        # tickt, schreiben wir die aktuelle Version ins Marker-File und der
        # Dialog erscheint erst beim nächsten Update wieder.
        if not as_help:
            self.cb_dont_show = QCheckBox(
                f"Bei diesem Update (v{__version__}) nicht erneut zeigen"
            )
            self.cb_dont_show.setChecked(True)
            layout.addWidget(self.cb_dont_show)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 6, 0, 0)
        btn_row.addStretch()
        cta_btn = QPushButton(cta_text)
        cta_btn.clicked.connect(self.accept)
        cta_btn.setDefault(True)
        # primary-Property triggert das iOS-Blue-Stylesheet von oben.
        cta_btn.setProperty("primary", True)
        btn_row.addWidget(cta_btn)
        layout.addLayout(btn_row)

    def accept(self) -> None:
        # Marker nur im Welcome-Modus schreiben — der Help-Modus darf den
        # Onboarding-Status nicht beeinflussen (sonst koennte ein User der
        # zum ersten Mal "Anleitung..." aus dem Tray öffnet versehentlich
        # den Welcome-Dialog beim nächsten Start überspringen).
        if not self._as_help and getattr(self, "cb_dont_show", None) is not None:
            if self.cb_dont_show.isChecked():
                mark_welcomed()
        super().accept()
