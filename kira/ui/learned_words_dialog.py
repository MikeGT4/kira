# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Fenster „Gelernte Wörter": wartende Paare freigeben, aktive löschen.

Oben die Korrekturquote (diese Woche, Vorwoche, Ausgangswert), darunter zwei
Listen. Jede Entscheidung wird sofort gespeichert und wirkt ohne Neustart.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from kira._resources import assets_dir
from kira.lexicon import Entry
from kira.ui._dialog_style import apply_light_theme

log = logging.getLogger(__name__)
_ASSETS = assets_dir()
KIND_LABELS = {"replacement": "Ersetzung", "glossary": "Glossar"}
COLUMNS = ("Erkannt", "Richtig", "Art", "Anzahl", "Beispiel")
NO_SOURCES_HINT = (
    "Keine Lernquellen eingetragen (learning.sources in der Rohconfig). "
    "Kira schreibt nur den Verlauf."
)

# Vorbild-Maßtabelle (Spec §5 „Oberfläche"): Knopf-Mindestbreite 120 px und
# Abstand 8 px zwischen Knöpfen einer Reihe, nur in diesem Fenster. Die
# übrigen Kira-Dialoge bleiben bei den 80 px aus kira/ui/_dialog_style.py.
_BUTTON_MIN_WIDTH = 120
_BUTTON_ROW_SPACING = 8

# apply_light_theme() (kira/ui/_dialog_style.py) deckt weder QTableWidget noch
# QHeaderView ab, darum blieben beide im dunklen Windows-11-Standardstil
# (Befund aus dem Screenshot-Abgleich der ersten Fassung). Hier lokal
# nachgezogen, nur für dieses Fenster.
_TABLE_QSS = (
    "QTableWidget {"
    " background: #ffffff;"
    " color: #222;"
    " border: 1px solid #c0c0c0;"
    " border-radius: 4px;"
    " gridline-color: #e5e5e5;"
    "}"
    "QTableWidget::item:selected {"
    " background: #cce4f7;"
    " color: #222;"
    "}"
    "QHeaderView::section {"
    " background: #f3f3f3;"
    " color: #222;"
    " border: none;"
    " border-bottom: 1px solid #d0d0d0;"
    " padding: 4px 6px;"
    "}"
    "QTableCornerButton::section {"
    " background: #f3f3f3;"
    " border: none;"
    "}"
)


def format_rate(value: tuple[int, int] | None) -> str:
    if not value or value[1] == 0:
        return "noch keine Daten"
    corrected, matched = value
    percent = f"{corrected / matched * 100:.1f}".replace(".", ",")
    return f"{percent} % ({corrected} von {matched})"


class LearnedWordsDialog(QDialog):
    def __init__(self, service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.setWindowTitle("Kira: Gelernte Wörter")
        icon_path = _ASSETS / "icon-branded.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumWidth(820)
        self.setModal(True)
        apply_light_theme(self)
        # _dialog_style._QSS setzt "QPushButton { min-width: 80px; }" für
        # alle Dialoge. Diese Zeile hängt eine gleich spezifische Regel an
        # dieselbe, dialog-lokale Stylesheet-Zeichenkette an: bei gleicher
        # Spezifität gewinnt in der Qt-Stylesheet-Kaskade die zuletzt
        # geparste Deklaration, hier also 120 statt 80 px, nur für dieses
        # Fenster. _dialog_style.py selbst bleibt unverändert.
        self.setStyleSheet(
            self.styleSheet()
            + f"QPushButton {{ min-width: {_BUTTON_MIN_WIDTH}px; }}"
            + _TABLE_QSS
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)
        outer.addWidget(self._build_header())

        self.metrics_label = QLabel()
        self.metrics_label.setWordWrap(True)
        outer.addWidget(self.metrics_label)

        outer.addWidget(self._section_title("Wartet auf dich"))
        self.pending_table = self._make_table()
        outer.addWidget(self.pending_table)
        self.accept_button = QPushButton("Übernehmen")
        self.reject_button = QPushButton("Verwerfen")
        # Kein Knopf in den beiden Listen darf der Dialog-Default sein, sonst
        # löscht oder verwirft ein bloßes Enter versehentlich ein Paar. Der
        # Default ist der harmlose Schließen-Knopf ganz unten.
        self.accept_button.setAutoDefault(False)
        self.reject_button.setAutoDefault(False)
        outer.addLayout(self._button_row(self.reject_button, self.accept_button))

        outer.addWidget(self._section_title("Aktiv"))
        self.active_table = self._make_table()
        outer.addWidget(self.active_table)
        self.delete_button = QPushButton("Löschen")
        self.delete_button.setAutoDefault(False)
        outer.addLayout(self._button_row(self.delete_button))

        # Zusätzlicher Abstand vor dem Schließen-Knopf: er zählt zum Dialog
        # als Ganzes, nicht zur "Aktiv"-Liste darüber, und soll optisch davon
        # abgesetzt sein (zusätzlich zu outer.setSpacing(12)).
        outer.addSpacing(12)
        close_button = QPushButton("Schließen")
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        outer.addLayout(self._button_row(close_button))

        self.accept_button.clicked.connect(lambda: self._decide(self.pending_table, "accept"))
        self.reject_button.clicked.connect(lambda: self._decide(self.pending_table, "reject"))
        self.delete_button.clicked.connect(lambda: self._decide(self.active_table, "reject"))
        self.refresh()

    def _build_header(self) -> QWidget:
        from kira.ui.settings_dialog import _load_branded_pixmap
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 4)
        row.setSpacing(12)
        glyph = QLabel()
        pix = _load_branded_pixmap(48)
        if pix is not None:
            glyph.setPixmap(pix)
        row.addWidget(glyph)
        row.addStretch()
        title = QLabel("Gelernte Wörter")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        row.addWidget(title)
        row.addStretch()
        logo = QLabel()
        logo_path = _ASSETS / "digitalroots-logo.png"
        if logo_path.exists():
            logo.setPixmap(QPixmap(str(logo_path)).scaledToHeight(
                26, Qt.TransformationMode.SmoothTransformation,
            ))
        row.addWidget(logo)
        return host

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        font = QFont()
        font.setBold(True)
        label.setFont(font)
        return label

    @staticmethod
    def _button_row(*buttons: QPushButton) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(_BUTTON_ROW_SPACING)
        row.addStretch()
        for button in buttons:
            button.setMinimumWidth(_BUTTON_MIN_WIDTH)
            row.addWidget(button)
        return row

    @staticmethod
    def _make_table() -> QTableWidget:
        table = QTableWidget(0, len(COLUMNS))
        table.setHorizontalHeaderLabels(COLUMNS)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        return table

    @staticmethod
    def _fill(table: QTableWidget, entries: list[Entry]) -> None:
        table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            values = (
                entry.wrong, entry.right, KIND_LABELS.get(entry.kind, entry.kind),
                str(entry.count), entry.example,
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, list(entry.key))
                table.setItem(row, col, item)

    def refresh(self) -> None:
        lexicon = self._service.lexicon
        self._fill(self.pending_table, lexicon.pending())
        self._fill(self.active_table, lexicon.active())
        metrics = self._service.metrics()
        text = (
            f"Korrekturquote diese Woche: {format_rate(metrics.get('this_week'))} · "
            f"Vorwoche: {format_rate(metrics.get('last_week'))} · "
            f"Ausgangswert: {format_rate(metrics.get('baseline'))}\n"
            f"Zuordnung diese Woche: {format_rate(metrics.get('coverage'))}"
        )
        # Dienste ohne die Eigenschaft (ältere Test-Attrappen) gelten als mit Quellen.
        if not getattr(self._service, "has_sources", True):
            text += "\n" + NO_SOURCES_HINT
        self.metrics_label.setText(text)

    def _selected_keys(self, table: QTableWidget) -> list[tuple[str, str]]:
        keys: list[tuple[str, str]] = []
        for index in table.selectionModel().selectedRows():
            item = table.item(index.row(), 0)
            if item is not None:
                keys.append(tuple(item.data(Qt.ItemDataRole.UserRole)))
        return keys

    def _decide(self, table: QTableWidget, action: str) -> None:
        keys = self._selected_keys(table)
        if not keys:
            return
        lexicon = self._service.lexicon
        for key in keys:
            getattr(lexicon, action)(key)
        try:
            lexicon.save()
        except OSError:
            log.exception("Lernen: Speichern nach Entscheidung fehlgeschlagen")
        self.refresh()
