"""Light theme for Kira's modal Qt dialogs.

Win11 dark mode propagates into Qt6 by default. The dark backdrop
swallowed the digital-roots logo (black artwork on transparent canvas)
and rendered button text white-on-light when we forced a light BG via
stylesheet only. QPalette covers Window/Base/Button/Text consistently
so labels, checkboxes, push-buttons, and form controls all flip to
light without per-widget styling — important for SettingsDialog whose
QComboBox / QSpinBox would render badly under a tight QSS override.
"""
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QDialog


def _light_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#f7f7f7"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#222"))
    p.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#f0f0f0"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#222"))
    p.setColor(QPalette.ColorRole.Text, QColor("#222"))
    p.setColor(QPalette.ColorRole.Button, QColor("#fafafa"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#222"))
    p.setColor(QPalette.ColorRole.BrightText, QColor("#cc0000"))
    p.setColor(QPalette.ColorRole.Link, QColor("#0d6efd"))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#1976d2"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#888"))
    return p


# Label / checkbox text colors must be respecified in QSS — Qt drops
# back to the system palette for un-styled widgets, but Win11's Fluent
# style overrides the palette's WindowText color with its own dark-mode
# value. Once we set ANY stylesheet on the dialog, every visible widget
# loses its native theming and we have to spell out the colors that
# mattered. QPushButton needs a full restyle (Fluent renders Win11 buttons
# as transparent rectangles by default). Form controls aren't covered —
# SettingsDialog's QComboBox/QSpinBox keep their native look on purpose.
_QSS = (
    "QLabel { color: #222; background: transparent; }"
    "QCheckBox { color: #222; background: transparent; }"
    "QPushButton {"
    " background: #ffffff;"
    " border: 1px solid #c0c0c0;"
    " padding: 6px 18px;"
    " border-radius: 4px;"
    " color: #222;"
    " min-width: 80px;"
    "}"
    "QPushButton:hover { background: #ececec; }"
    "QPushButton:default { border: 1px solid #1976d2; background: #e8f1ff; }"
    "QPushButton:pressed { background: #d8e6f7; }"
)


def apply_light_theme(dialog: QDialog) -> None:
    dialog.setPalette(_light_palette())
    dialog.setStyleSheet(_QSS)
