"""Modal setup-hint dialog: shown when mic or Ollama isn't ready.

Replaces the Win32 MessageBoxW that welcome_win.py used to call. Same
digital-roots logo + copyright look as AboutDialog and WelcomeDialog so
all Kira pop-ups feel like one app.
"""
from __future__ import annotations
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"


class SetupHintDialog(QDialog):
    """Setup hint shown when mic or Ollama isn't ready."""

    def __init__(self, mic_ok: bool, ollama_ok: bool) -> None:
        super().__init__()
        self.setWindowTitle("Kira Setup")
        icon_path = _ASSETS / "icon-branded.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setFixedSize(560, 500)
        self.setModal(True)
        from kira.ui._dialog_style import apply_light_theme
        apply_light_theme(self)
        self.user_clicked_open_mic_settings = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        logo_label = QLabel()
        logo_path = _ASSETS / "digitalroots-logo.png"
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaledToWidth(
                400, Qt.TransformationMode.SmoothTransformation
            )
            logo_label.setPixmap(pix)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_label)

        heading = QLabel("Kira braucht noch etwas Setup")
        heading_font = QFont()
        heading_font.setPointSize(16)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        issues: list[str] = []
        if not mic_ok:
            issues.append(
                "<b>Mikrofon-Zugriff fehlt</b><br>"
                "Kira braucht Zugriff aufs Mikrofon, um deine Stimme aufzunehmen."
            )
        if not ollama_ok:
            issues.append(
                "<b>Ollama nicht erreichbar</b> unter "
                "<code>http://localhost:11434</code><br>"
                "Bitte stelle sicher, dass Ollama läuft. Ohne Ollama "
                "fügt Kira den unpolierten Whisper-Text ein."
            )
        body = QLabel("<br><br>".join(issues))
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body_font = QFont()
        body_font.setPointSize(10)
        body.setFont(body_font)
        layout.addWidget(body)

        layout.addStretch()

        legal = QLabel("© 2026 Mike Pollow / digitalroots")
        legal_font = QFont()
        legal_font.setPointSize(8)
        legal.setFont(legal_font)
        legal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(legal)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        if not mic_ok:
            mic_btn = QPushButton("Mikrofon-Einstellungen öffnen")
            mic_btn.clicked.connect(self._on_mic_clicked)
            btn_row.addWidget(mic_btn)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_mic_clicked(self) -> None:
        self.user_clicked_open_mic_settings = True
        self.accept()
