"""First-run welcome dialog AND on-demand "Anleitung" via Tray-Menue.

Ein Dialog, zwei Modi:

- as_help=False (default): Welcome-Modus. Wird beim ersten Start gezeigt
  wenn die installierte Version groesser ist als die im Marker
  vermerkte. Mit "Loslegen"-Button + "Bei diesem Update nicht mehr
  zeigen"-Checkbox (default ticked).

- as_help=True: Help-Modus. Aus dem Tray-Menue ("Anleitung...") oder
  dem Hilfe-Button im Settings-Dialog aufgerufen. Title = "Anleitung",
  kein Checkbox/Marker-Write, nur "Schliessen"-Button.

Versions-aware Marker (seit v0.2): %APPDATA%\\Kira\\.welcomed enthaelt
die Version-Number, die der User zuletzt durchgewinkt hat. Bei jedem
Boot vergleichen wir vs __version__ — wenn die installierte Version
groesser ist (User hat upgegradet), zeigen wir den Dialog erneut
("Was ist neu in vX.Y.Z?"). Old-style Marker (Inhalt "welcomed" aus
v0.1.0) faellt unter "kann nicht geparst werden" und triggert den
Dialog ein letztes Mal — danach steht die Version drin.
"""
from __future__ import annotations
import logging
import os
from pathlib import Path

from packaging.version import InvalidVersion, parse as parse_version
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


def is_first_run() -> bool:
    """True wenn der User die aktuelle Version noch nicht durchgewinkt hat.

    - Marker fehlt → True (echter erster Start)
    - Marker existiert mit gueltiger Version >= __version__ → False
    - Marker existiert mit gueltiger Version < __version__ → True (Upgrade)
    - Marker existiert mit ungueltiger Version (v0.1-Stil "welcomed") → True
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
    """Schreibe die aktuelle Version in den Marker. Beim naechsten Boot
    mit derselben Version wird is_first_run False; nach Major/Minor-Bump
    zeigt sich der Dialog wieder ('Was ist neu')."""
    _WELCOME_MARKER.parent.mkdir(parents=True, exist_ok=True)
    _WELCOME_MARKER.write_text(__version__, encoding="utf-8")


_GUIDE_HTML = """
<p>Kira ist dein lokaler Sprache-zu-Text-Helfer. Alles laeuft auf deinem PC —
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

<h3>2. AI-Editing-Commands (Selektion ueberarbeiten)</h3>
<ul>
  <li>Markiere Text in einer beliebigen App.</li>
  <li>Halte <b>F9</b> und sage einen Befehl:
    „mach das foermlich" / „uebersetz auf Englisch" /
    „fass das in 3 Bullets zusammen".</li>
  <li>Lass F9 los — die Selektion wird durch den ueberarbeiteten Text ersetzt.</li>
</ul>
<p style='color:#666; font-size:11px;'>F9 nutzt Strg+C im Hintergrund.
Wenn nichts selektiert ist, ist der Hotkey ein No-Op.</p>

<h3>3. Datei transkribieren</h3>
<p>Tray-Icon (rechts unten) → Rechtsklick → <b>„Datei transkribieren..."</b>.
Audio (.wav, .mp3, .m4a, .flac, .ogg, .opus) oder Video
(.mp4, .mov, .mkv, .webm) auswaehlen — Kira speichert die Transkription
als <code>.txt</code> neben der Eingabedatei.</p>

<h3>4. Modi &amp; Custom Dictionary</h3>
<p>Kira erkennt automatisch in welcher App du tippst (Outlook → foermliche
Email, Slack → lockerer Chat, VS Code → Code) und nutzt unterschiedliche
Polish-Prompts. Eingebaute Modi:
<code>email</code>, <code>chat</code>, <code>code</code>,
<code>terminal</code>, <code>plain</code>, <code>clean</code>
(Filler-Filter only),
<code>translate_en</code> (Deutsch→Englisch),
<code>email_formal</code> (Sie-Form, Praxis-Stil).</p>
<p>Eigennamen werden oft falsch transkribiert (z.B. „im Mediku" statt
„im medicum"). In Settings → „Rohconfig oeffnen..." kannst du eine
Replacement-Map setzen:</p>
<pre style='background:#f4f4f4; padding:8px; border-radius:4px; font-size:10px;'>
whisper:
  replacements:
    "im mediku": "im medicum"
    "frau schmid": "Frau Schmidt"
</pre>

<h3>5. Updates</h3>
<p>Tray → <b>„Updates suchen..."</b> oder Settings → „Ueber Kira" → Update-Button.
Kira prueft GitHub Releases, laedt das Multi-Asset-Bundle (Stub + Splits),
verifiziert SHA256-Hashes (falls im Release vorhanden), und startet den
Setup-Wizard. Kira beendet sich dafuer kurz.</p>

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
Komplexe Felder (Replacements, Modi, Initial-Prompt) ueber „Rohconfig oeffnen...".</p>

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
            cta_text = "Schliessen"
        else:
            self.setWindowTitle("Willkommen bei Kira")
            heading_text = "Willkommen bei Kira"
            cta_text = "Loslegen"

        icon_path = _ASSETS / "icon-branded.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(640, 600)
        self.resize(680, 720)
        self.setModal(True)
        from kira.ui._dialog_style import apply_light_theme
        apply_light_theme(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(12)

        # Logo (digitalroots, klein gehalten — Help-Modus zeigt es auch fuer
        # konsistente Branding-Identitaet; kostet 30 px und macht den Dialog
        # weniger nuechtern).
        logo_label = QLabel()
        logo_path = _ASSETS / "digitalroots-logo.png"
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaledToWidth(
                360, Qt.TransformationMode.SmoothTransformation,
            )
            logo_label.setPixmap(pix)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_label)

        heading = QLabel(heading_text)
        heading_font = QFont()
        heading_font.setPointSize(18)
        heading_font.setBold(True)
        heading.setFont(heading_font)
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
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; } "
            "QLabel { padding: 0 4px; }"
        )
        layout.addWidget(scroll, stretch=1)

        # Checkbox nur im Welcome-Modus — im Help-Modus waere "nicht mehr
        # zeigen" sinnfrei (er wird ja nur on-demand geoeffnet).
        # Text-Fassung passt zur version-aware Marker-Logik: wenn der User
        # tickt, schreiben wir die aktuelle Version ins Marker-File und der
        # Dialog erscheint erst beim naechsten Update wieder.
        if not as_help:
            self.cb_dont_show = QCheckBox(
                f"Bei diesem Update (v{__version__}) nicht erneut zeigen"
            )
            self.cb_dont_show.setChecked(True)
            layout.addWidget(self.cb_dont_show)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cta_btn = QPushButton(cta_text)
        cta_btn.clicked.connect(self.accept)
        cta_btn.setDefault(True)
        btn_row.addWidget(cta_btn)
        layout.addLayout(btn_row)

    def accept(self) -> None:
        # Marker nur im Welcome-Modus schreiben — der Help-Modus darf den
        # Onboarding-Status nicht beeinflussen (sonst koennte ein User der
        # zum ersten Mal "Anleitung..." aus dem Tray oeffnet versehentlich
        # den Welcome-Dialog beim naechsten Start ueberspringen).
        if not self._as_help and getattr(self, "cb_dont_show", None) is not None:
            if self.cb_dont_show.isChecked():
                mark_welcomed()
        super().accept()
