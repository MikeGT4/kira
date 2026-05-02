"""Modal About dialog with the branded header + runtime stack info.

Triggered from the tray menu's 'About Kira'. Header layout matches
SettingsDialog (yellow Kira-branded glyph left, title centred,
digitalroots wordmark right) so the dialog reads as part of the same
app family. The earlier kira-splash.png header was dropped because its
in-image '© 2026 by Digitalroots' footer text didn't match house
spelling.
"""
from __future__ import annotations
import logging
from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from kira import UPDATE_REPO, __version__
from kira.config import effective_hotkey

log = logging.getLogger(__name__)
_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"


def _load_branded_pixmap(size: int) -> QPixmap | None:
    """Largest-frame ICO loader (Pillow → QPixmap). QPixmap's native ICO
    plugin defaults to a small frame and upscales — that left the
    branded glyph blurry at 48 px until we explicitly picked the 256
    frame and downscaled once."""
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
        log.exception("failed to load icon-branded.ico for About header")
        return None


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
        icon_path = _ASSETS / "icon-branded.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setFixedSize(600, 640)
        self.setModal(True)
        from kira.ui._dialog_style import apply_light_theme
        apply_light_theme(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        outer.addWidget(self._build_header())

        # Stack-info form, indented from the dialog edges.
        cfg = _safe_load_config()
        whisper_model_name = Path(cfg.whisper.model).name or cfg.whisper.model
        mic_label = (
            str(cfg.audio.input_device)
            if cfg.audio.input_device is not None
            else "Windows-Default"
        )

        form_block = QVBoxLayout()
        form_block.setContentsMargins(20, 4, 20, 6)
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
            f"© 2026 Mike Pollow · digitalroots — Personal-Use-Lizenz"
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

    def _build_header(self) -> QWidget:
        # Same Kira-glyph + title + digitalroots layout as SettingsDialog,
        # so both tray-menu dialogs share one visual identity.
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

        title = QLabel("Über Kira")
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
