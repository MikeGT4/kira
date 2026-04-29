"""Modal About dialog with the branded Kira splash + runtime stack info.

Triggered from the tray menu's 'About Kira'. Replaces the bare logo +
version layout with the full kira-splash header followed by a concise
stack-info form (model, polish-LLM, hotkey, mic) so users can see what
their install is actually running without opening the YAML config.
"""
from __future__ import annotations
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from kira import UPDATE_REPO, __version__
from kira.config import effective_hotkey


_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"


def _safe_load_config():
    """Best-effort config load — fall back to defaults so the dialog
    still renders even if the YAML is malformed."""
    try:
        from kira.config import load_config
        return load_config()
    except Exception:
        from kira.config import Config
        return Config()


class AboutDialog(QDialog):
    """About Kira: branded header + stack info."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Über Kira")
        icon_path = _ASSETS / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setFixedSize(600, 640)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Branded splash header — flush to the dialog edges.
        splash_label = QLabel()
        splash_path = _ASSETS / "kira-splash.png"
        if splash_path.exists():
            pix = QPixmap(str(splash_path)).scaledToWidth(
                600, Qt.TransformationMode.SmoothTransformation
            )
            splash_label.setPixmap(pix)
        else:
            # Graceful fallback: plain title block if asset is missing.
            splash_label.setText("<h1 style='margin:32px;'>Kira</h1>")
        splash_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(splash_label)

        # Stack-info form, indented from the dialog edges.
        cfg = _safe_load_config()
        whisper_model_name = Path(cfg.whisper.model).name or cfg.whisper.model
        mic_label = (
            str(cfg.audio.input_device)
            if cfg.audio.input_device is not None
            else "Windows-Default"
        )

        form_block = QVBoxLayout()
        form_block.setContentsMargins(40, 18, 40, 6)
        form_block.setSpacing(6)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(6)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        def _row(label: str, value: str) -> None:
            label_widget = QLabel(f"<b>{label}</b>")
            value_widget = QLabel(value)
            value_widget.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            value_widget.setWordWrap(True)
            form.addRow(label_widget, value_widget)

        _row("Version", f"v{__version__}")
        _row("Speech-to-Text", f"faster-whisper · {whisper_model_name}")
        _row("Polish-LLM", f"{cfg.styler.model} ({cfg.styler.provider})")
        _row("Hotkey", f"{effective_hotkey(cfg.hotkey.combo).upper()} halten")
        _row("Mikrofon", mic_label)
        form_block.addLayout(form)

        outer.addLayout(form_block)

        # Footer: GitHub link + copyright/license, then close button.
        footer = QLabel(
            f"<div style='margin-top:8px;'>"
            f"<a href='https://github.com/{UPDATE_REPO}'>"
            f"github.com/{UPDATE_REPO}</a>"
            f"<br><span style='color:#888; font-size:11px;'>"
            f"© 2026 Mike Pollow · digital roots — Personal-Use-Lizenz"
            f"</span></div>"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setOpenExternalLinks(True)
        outer.addWidget(footer)

        outer.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(24, 8, 24, 18)
        btn_row.addStretch()
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)
