"""First-run welcome dialog. Shown once when %APPDATA%\\Kira\\.welcomed is missing.

Mounted from main._run_windows() right after the QApplication is created
so the tray icon and hotkey listener don't spin up before the user has
seen the welcome. Marker file gets written when the user clicks Loslegen
with the 'don't show again' checkbox ticked (default on).
"""
from __future__ import annotations
import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
_WELCOME_MARKER = Path(os.environ.get("APPDATA", str(Path.home()))) / "Kira" / ".welcomed"


def is_first_run() -> bool:
    """True iff the welcome marker file does not exist yet."""
    return not _WELCOME_MARKER.exists()


def mark_welcomed() -> None:
    """Create the welcome marker so subsequent starts skip the welcome."""
    _WELCOME_MARKER.parent.mkdir(parents=True, exist_ok=True)
    _WELCOME_MARKER.write_text("welcomed", encoding="utf-8")


class WelcomeDialog(QDialog):
    """One-shot welcome screen for the first Kira launch."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Willkommen bei Kira")
        icon_path = _ASSETS / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setFixedSize(620, 540)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        logo_label = QLabel()
        logo_path = _ASSETS / "digitalroots-logo.png"
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaledToWidth(
                460, Qt.TransformationMode.SmoothTransformation
            )
            logo_label.setPixmap(pix)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_label)

        heading = QLabel("Willkommen bei Kira")
        heading_font = QFont()
        heading_font.setPointSize(20)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        body = QLabel(
            "Kira ist dein lokaler Sprache-zu-Text-Helfer.<br><br>"
            "<b>So benutzt du Kira:</b><br>"
            "1. Halte <b>F8</b> in jedem beliebigen Programm.<br>"
            "2. Sprich, was du tippen willst.<br>"
            "3. Lass F8 los — der polierte Text erscheint dort, wo dein Cursor steht.<br><br>"
            "Kira läuft im <b>Tray</b> (rechts unten neben der Uhr). Klicke das Icon "
            "für Optionen, Update-Check und „Quit Kira‟."
        )
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body_font = QFont()
        body_font.setPointSize(10)
        body.setFont(body_font)
        layout.addWidget(body)

        layout.addStretch()

        self.cb_dont_show = QCheckBox("Diesen Dialog nicht mehr zeigen")
        self.cb_dont_show.setChecked(True)
        layout.addWidget(self.cb_dont_show)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        start_btn = QPushButton("Loslegen")
        start_btn.clicked.connect(self.accept)
        start_btn.setDefault(True)
        btn_row.addWidget(start_btn)
        layout.addLayout(btn_row)

    def accept(self) -> None:
        if self.cb_dont_show.isChecked():
            mark_welcomed()
        super().accept()
