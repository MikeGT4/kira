"""First-Run Setup-Wizard fuer Kira (Windows).

Wird beim ersten Start (Marker-File abwesend, siehe `kira.firstrun`) vom
Slim-Installer-Build aufgerufen. Drei Steps:

1. Whisper-Modell von Hugging Face Hub pullen (~3 GB) via
   `huggingface_hub.snapshot_download` mit Resume-Support.
2. Ollama-Backend installieren falls noch nicht da, sonst skippen
   (idempotent).
3. Gemma-Modell pullen (~8 GB, `ollama pull gemma3:12b`) — skippen
   wenn `ollama list` den Tag bereits zeigt.

Architektur:
- 3 QThread-Worker fuer die 3 Steps. Direkt-aufrufbares run() ohne
  QEventLoop, daher in Tests synchron pruefbar.
- 3 QWizardPages: Welcome / Download / Finished.
- DownloadPage startet Whisper- und Ollama-Worker parallel; Gemma-Worker
  sequenziell NACH Ollama-Done (braucht das CLI).
- Marker via `mark_first_run_complete()` NUR bei Total-Erfolg
  (SetupWizard.accept()) — abgebrochen oder mit Fehler -> Marker NICHT
  gesetzt -> Wizard erscheint beim naechsten Start wieder.

Sicherheit:
- Subprocess: IMMER list-args, NIE shell=True (siehe Cleanup-Notes
  CLAUDE.md). `_resource_path`-Pfade kommen aus Inno-Bundle, sind
  programmgenerated, nicht user-supplied.
- Ollama-API-URL ist hart 127.0.0.1 (NICHT localhost) — Win11 24H2+
  resolved localhost zu IPv6 ::1, Ollama bindet IPv4 0.0.0.0.

Spec: docs/superpowers/plans/2026-05-10-wsl-decoupling-and-installer-redesign.md
"""
from __future__ import annotations
import logging
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from huggingface_hub import snapshot_download
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QLabel,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from kira.firstrun import mark_first_run_complete
from kira.ui._dialog_style import apply_light_theme

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-Konstanten
# ---------------------------------------------------------------------------

# IPv4-only — Win11 24H2+ resolved 'localhost' zu '::1' und Ollama bindet
# nur IPv4 (0.0.0.0:11434). Mit 'localhost' bekommt man ConnectionRefused
# obwohl der Service laeuft. Siehe Phase C3-Spec.
OLLAMA_API_URL = "http://127.0.0.1:11434/api/tags"

# Bundle-Default — non-turbo, weil Mike's German benchmark 2026-04
# Turbo bei Fachvokabular schwaecher zeigte. Im Wizard ueber den
# repo_id-Parameter overridebar.
DEFAULT_WHISPER_REPO = "Systran/faster-whisper-large-v3"

DEFAULT_GEMMA_TAG = "gemma3:12b"

# Wait-Loop nach Ollama-Install: bis API erreichbar wird. 60 s sollten
# fuer einen Service-Start auf Win11 reichen. Je 1 s Tick.
_OLLAMA_API_WAIT_SECONDS = 60


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def is_ollama_installed() -> bool:
    """Prueft ob 'ollama' im PATH liegt (Win11 + Ollama-Installer setzt
    `%LOCALAPPDATA%\\Programs\\Ollama` als User-Path).
    """
    return shutil.which("ollama") is not None


def is_ollama_reachable(timeout: float = 3.0) -> bool:
    """HTTP-GET auf /api/tags. Service down -> ConnectionRefused/Timeout.

    Mike's Codebase nutzt `urllib.request` durchgehend (siehe updater.py),
    daher kein `requests`-Dep. ConnectionError-Familie wird als
    "nicht erreichbar" interpretiert, nicht als Fatal.
    """
    try:
        with urllib.request.urlopen(OLLAMA_API_URL, timeout=timeout) as response:  # noqa: S310 - hardcoded loopback URL
            return 200 <= response.status < 300
    except (urllib.error.URLError, ConnectionError, socket.timeout, OSError) as exc:
        log.debug("Ollama unreachable: %s", exc)
        return False


# ---------------------------------------------------------------------------
# WhisperDownloadWorker
# ---------------------------------------------------------------------------

class WhisperDownloadWorker(QThread):
    """Pullt das Whisper-Modell ueber huggingface_hub mit Resume-Support.

    huggingface_hub kennt selbst keinen Pre-Download-Size-Hook (es weiss
    die exakte File-Liste erst beim Streaming des Manifests), daher
    bleibt unser progress-Signal stub-haft — die UI zeigt
    'Whisper laedt...' und einen indeterminate Progress-Bar.
    """

    progress = pyqtSignal(int, int)   # (done_bytes, total_bytes) — best-effort
    status = pyqtSignal(str)          # human-readable Status-Line
    error = pyqtSignal(str)
    finished = pyqtSignal(Path)       # local path zum heruntergeladenen Modell

    def __init__(
        self,
        target_dir: Path,
        repo_id: str = DEFAULT_WHISPER_REPO,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._target_dir = Path(target_dir)
        self._repo_id = repo_id

    def run(self) -> None:
        log.info("Whisper-Download startet: repo=%s target=%s",
                 self._repo_id, self._target_dir)
        self.status.emit(f"Lade Whisper-Modell ({self._repo_id})...")
        self._target_dir.mkdir(parents=True, exist_ok=True)
        try:
            local_path = snapshot_download(
                repo_id=self._repo_id,
                local_dir=str(self._target_dir),
            )
        except Exception as exc:  # ConnectionError, HfHubHTTPError, etc.
            log.exception("Whisper-Download fehlgeschlagen")
            self.error.emit(f"Whisper-Download fehlgeschlagen: {type(exc).__name__}: {exc}")
            return

        log.info("Whisper-Download fertig: %s", local_path)
        self.status.emit("Whisper-Modell bereit.")
        self.finished.emit(Path(local_path))


# ---------------------------------------------------------------------------
# OllamaSetupWorker
# ---------------------------------------------------------------------------

class OllamaSetupWorker(QThread):
    """Installiert Ollama wenn noetig, sonst skip.

    Idempotenz-Check: `is_ollama_installed() AND is_ollama_reachable()`
    -> skip. Sonst Installer im Silent-Modus + Wait-Loop bis API
    antwortet. Bei Wait-Timeout -> error (Service kommt nicht hoch =
    Hardware/AV-Problem, manueller Eingriff noetig).
    """

    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, installer_path: Path, parent=None) -> None:
        super().__init__(parent)
        self._installer_path = Path(installer_path)

    def run(self) -> None:
        if is_ollama_installed() and is_ollama_reachable():
            log.info("Ollama bereits installiert + erreichbar -> skip install")
            self.status.emit("Ollama bereits installiert.")
            self.finished.emit()
            return

        if not self._installer_path.exists():
            msg = f"Ollama-Installer nicht gefunden: {self._installer_path}"
            log.error(msg)
            self.error.emit(msg)
            return

        self.status.emit("Installiere Ollama...")
        log.info("Starting Ollama installer: %s", self._installer_path)
        try:
            # Silent-Flags: /S (NSIS-Standard) + /NORESTART. KEIN shell=True,
            # IMMER list-args -> kein Command-Injection moeglich (auch wenn
            # _installer_path immer programmgenerated kommt).
            result = subprocess.run(  # noqa: S603 - list-args, kein shell-Parsing
                [str(self._installer_path), "/S", "/NORESTART"],
                timeout=300,
                check=False,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            self.error.emit("Ollama-Installer Timeout (>300 s).")
            return
        except OSError as exc:
            self.error.emit(f"Ollama-Installer-Start fehlgeschlagen: {exc}")
            return

        if result.returncode != 0:
            self.error.emit(
                f"Ollama-Installer Exit-Code {result.returncode}.\n\n"
                f"stderr: {result.stderr.strip() if result.stderr else '(leer)'}"
            )
            return

        # Wait-Loop bis die Service-API antwortet (ollama serve startet
        # oft erst nach ein paar Sekunden via Auto-Run-Entry).
        self.status.emit("Warte auf Ollama-Service...")
        for tick in range(_OLLAMA_API_WAIT_SECONDS):
            if is_ollama_reachable(timeout=2.0):
                log.info("Ollama-Service erreichbar nach %ds", tick)
                self.status.emit("Ollama bereit.")
                self.finished.emit()
                return
            time.sleep(1)

        self.error.emit(
            f"Ollama-Service kommt nach {_OLLAMA_API_WAIT_SECONDS}s nicht "
            "hoch. Bitte System neustarten und Wizard erneut ausfuehren."
        )


# ---------------------------------------------------------------------------
# GemmaPullWorker
# ---------------------------------------------------------------------------

class GemmaPullWorker(QThread):
    """`ollama pull <tag>` mit Line-Buffer fuer Progress-Output.

    Erst `ollama list` als Idempotenz-Check, dann Pull. Bei nonzero
    Returncode -> Error-Signal. Output-Lines vom Pull (z.B. 'pulling
    abc: 47%') gehen unveraendert via progress-Signal an die UI.
    """

    progress = pyqtSignal(str)   # rohe Line vom ollama-Pull-Output
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, model_tag: str = DEFAULT_GEMMA_TAG, parent=None) -> None:
        super().__init__(parent)
        self._model_tag = model_tag

    def run(self) -> None:
        # Schritt 1: ollama list. Falls schon da -> skip.
        self.status.emit(f"Pruefe ob {self._model_tag} bereits installiert ist...")
        try:
            list_result = subprocess.run(  # noqa: S603 - list-args
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, OSError) as exc:
            self.error.emit(
                f"`ollama list` fehlgeschlagen: {type(exc).__name__}: {exc}\n"
                "Ollama-Service evtl. nicht aktiv."
            )
            return

        if self._model_tag in list_result.stdout:
            log.info("Gemma %s bereits installiert -> skip pull", self._model_tag)
            self.status.emit(f"{self._model_tag} bereits installiert.")
            self.finished.emit()
            return

        # Schritt 2: ollama pull mit Line-Buffer.
        self.status.emit(f"Lade {self._model_tag} (~8 GB)...")
        log.info("Starting ollama pull %s", self._model_tag)
        try:
            proc = subprocess.Popen(  # noqa: S603 - list-args
                ["ollama", "pull", self._model_tag],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            self.error.emit(f"`ollama pull` Start fehlgeschlagen: {exc}")
            return

        try:
            assert proc.stdout is not None  # stdout=PIPE guarantees this
            for line in proc.stdout:
                line_clean = line.strip()
                if line_clean:
                    self.progress.emit(line_clean)
            returncode = proc.wait(timeout=1800)  # 30 min hard ceiling
        except subprocess.TimeoutExpired:
            proc.kill()
            self.error.emit(
                f"`ollama pull {self._model_tag}` ueberzogen 30 min Timeout."
            )
            return
        except OSError as exc:
            self.error.emit(f"`ollama pull` lese-Fehler: {exc}")
            return

        if returncode != 0:
            self.error.emit(
                f"`ollama pull {self._model_tag}` fehlgeschlagen "
                f"(Exit-Code {returncode})."
            )
            return

        log.info("Gemma %s installiert", self._model_tag)
        self.status.emit(f"{self._model_tag} bereit.")
        self.finished.emit()


# ---------------------------------------------------------------------------
# UI: WelcomePage
# ---------------------------------------------------------------------------

class WelcomePage(QWizardPage):
    """Erste Page: Begruessung + Hinweis auf Modell-Download."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Willkommen bei Kira")
        self.setSubTitle(
            "Voice-to-Text mit KI-Polish — gleich startklar."
        )

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Kira braucht beim ersten Start zwei KI-Modelle:\n\n"
            "  - Whisper (Spracherkennung, ~3 GB)\n"
            "  - Gemma (Text-Polish, ~8 GB)\n\n"
            "Zusammen ca. 11 GB Download. Internet erforderlich, einmalig.\n\n"
            "Klicke auf »Weiter«, um fortzufahren."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addStretch(1)


# ---------------------------------------------------------------------------
# UI: DownloadPage
# ---------------------------------------------------------------------------

class DownloadPage(QWizardPage):
    """Zweite Page: 3 parallele/sequentielle Downloads + Log.

    - Whisper + Ollama-Setup parallel (unabhaengig).
    - Gemma-Pull NACH Ollama-Done (braucht das CLI).
    - Alle 3 finished -> completeChanged emit -> 'Weiter'-Button enabled.
    - Bei error: rote Log-Zeile + KEIN Marker, User muss Wizard cancel
      und neu starten (oder Inno-Installer rerunen).
    """

    def __init__(self, whisper_target: Path, ollama_installer: Path, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Modelle werden installiert")
        self.setSubTitle("Bitte warten — bei Abbruch geht der Download verloren.")
        self.setCommitPage(True)  # ab hier kein Back-Button mehr

        self._whisper_target = whisper_target
        self._ollama_installer = ollama_installer

        self._whisper_done = False
        self._ollama_done = False
        self._gemma_done = False

        self._whisper_worker: WhisperDownloadWorker | None = None
        self._ollama_worker: OllamaSetupWorker | None = None
        self._gemma_worker: GemmaPullWorker | None = None

        # --- Layout ---
        outer = QVBoxLayout(self)

        self._whisper_status = QLabel("Whisper: warte...")
        self._whisper_bar = QProgressBar()
        self._whisper_bar.setRange(0, 0)  # indeterminate
        outer.addWidget(self._whisper_status)
        outer.addWidget(self._whisper_bar)

        self._ollama_status = QLabel("Ollama: warte...")
        self._ollama_bar = QProgressBar()
        self._ollama_bar.setRange(0, 0)
        outer.addWidget(self._ollama_status)
        outer.addWidget(self._ollama_bar)

        self._gemma_status = QLabel("Gemma: warte (haengt von Ollama ab)")
        self._gemma_bar = QProgressBar()
        self._gemma_bar.setRange(0, 0)
        outer.addWidget(self._gemma_status)
        outer.addWidget(self._gemma_bar)

        log_label = QLabel("Log:")
        log_label.setFont(QFont())
        outer.addWidget(log_label)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(120)
        outer.addWidget(self._log, stretch=1)

    def isComplete(self) -> bool:  # noqa: N802 - Qt API
        return self._whisper_done and self._ollama_done and self._gemma_done

    def initializePage(self) -> None:
        """Wird beim Eintritt in die Page von Qt aufgerufen."""
        self._append_log("Starte Downloads...")

        # Whisper + Ollama parallel
        self._whisper_worker = WhisperDownloadWorker(
            target_dir=self._whisper_target,
        )
        self._whisper_worker.status.connect(self._on_whisper_status)
        self._whisper_worker.error.connect(self._on_whisper_error)
        self._whisper_worker.finished.connect(self._on_whisper_finished)

        self._ollama_worker = OllamaSetupWorker(
            installer_path=self._ollama_installer,
        )
        self._ollama_worker.status.connect(self._on_ollama_status)
        self._ollama_worker.error.connect(self._on_ollama_error)
        self._ollama_worker.finished.connect(self._on_ollama_finished)

        self._whisper_worker.start()
        self._ollama_worker.start()

    # --- Whisper signals ---
    def _on_whisper_status(self, msg: str) -> None:
        self._whisper_status.setText(f"Whisper: {msg}")
        self._append_log(f"[Whisper] {msg}")

    def _on_whisper_finished(self, path: Path) -> None:
        self._whisper_status.setText(f"Whisper: fertig ({path.name})")
        self._whisper_bar.setRange(0, 1)
        self._whisper_bar.setValue(1)
        self._whisper_done = True
        self._append_log(f"[Whisper] OK -> {path}")
        self.completeChanged.emit()

    def _on_whisper_error(self, msg: str) -> None:
        self._whisper_status.setText("Whisper: FEHLER")
        self._append_log(f"[Whisper FEHLER] {msg}", error=True)
        # KEIN finished -> isComplete bleibt False -> User kann nicht weiter

    # --- Ollama signals ---
    def _on_ollama_status(self, msg: str) -> None:
        self._ollama_status.setText(f"Ollama: {msg}")
        self._append_log(f"[Ollama] {msg}")

    def _on_ollama_finished(self) -> None:
        self._ollama_status.setText("Ollama: fertig")
        self._ollama_bar.setRange(0, 1)
        self._ollama_bar.setValue(1)
        self._ollama_done = True
        self._append_log("[Ollama] OK")
        self.completeChanged.emit()
        # Sequenzielle Kette: jetzt erst kann Gemma starten
        self._start_gemma()

    def _on_ollama_error(self, msg: str) -> None:
        self._ollama_status.setText("Ollama: FEHLER")
        self._append_log(f"[Ollama FEHLER] {msg}", error=True)

    # --- Gemma signals ---
    def _start_gemma(self) -> None:
        self._gemma_status.setText("Gemma: starte...")
        self._gemma_worker = GemmaPullWorker(model_tag=DEFAULT_GEMMA_TAG)
        self._gemma_worker.status.connect(self._on_gemma_status)
        self._gemma_worker.progress.connect(self._on_gemma_progress)
        self._gemma_worker.error.connect(self._on_gemma_error)
        self._gemma_worker.finished.connect(self._on_gemma_finished)
        self._gemma_worker.start()

    def _on_gemma_status(self, msg: str) -> None:
        self._gemma_status.setText(f"Gemma: {msg}")
        self._append_log(f"[Gemma] {msg}")

    def _on_gemma_progress(self, line: str) -> None:
        # ollama-pull-Output ist relativ chatty — nur ins Log, nicht
        # ins Status-Label (das wuerde wild flackern).
        self._append_log(f"[Gemma] {line}")

    def _on_gemma_finished(self) -> None:
        self._gemma_status.setText("Gemma: fertig")
        self._gemma_bar.setRange(0, 1)
        self._gemma_bar.setValue(1)
        self._gemma_done = True
        self._append_log("[Gemma] OK")
        self.completeChanged.emit()

    def _on_gemma_error(self, msg: str) -> None:
        self._gemma_status.setText("Gemma: FEHLER")
        self._append_log(f"[Gemma FEHLER] {msg}", error=True)

    # --- Log helper ---
    def _append_log(self, msg: str, error: bool = False) -> None:
        if error:
            self._log.append(f'<span style="color:#cc0000">{msg}</span>')
        else:
            self._log.append(msg)

    # --- Cleanup bei Abort ---
    def cleanupPage(self) -> None:
        """Wird von Qt aufgerufen wenn der User Back oder Cancel klickt."""
        self._stop_all_workers()

    def _stop_all_workers(self) -> None:
        for worker in (self._whisper_worker, self._ollama_worker, self._gemma_worker):
            if worker is not None and worker.isRunning():
                worker.quit()
                worker.wait(2000)


# ---------------------------------------------------------------------------
# UI: FinishedPage
# ---------------------------------------------------------------------------

class FinishedPage(QWizardPage):
    """Letzte Page: kurze Quick-Start-Hinweise."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Setup abgeschlossen")
        self.setSubTitle("Kira ist bereit.")

        layout = QVBoxLayout(self)
        hints = QLabel(
            "So funktioniert's:\n\n"
            "  - F8 gedrueckt halten -> sprechen -> loslassen.\n"
            "    Dein Text erscheint am Cursor.\n\n"
            "  - F9 markieren + halten -> Sprach-Befehl auf den\n"
            "    markierten Text (z.B. 'mach den Text formeller').\n\n"
            "  - Tray-Icon (rechts unten) -> Einstellungen,\n"
            "    Anleitung, Updates.\n\n"
            "Klicke auf »Fertigstellen«, um Kira zu starten."
        )
        hints.setWordWrap(True)
        layout.addWidget(hints)
        layout.addStretch(1)


# ---------------------------------------------------------------------------
# SetupWizard
# ---------------------------------------------------------------------------

class SetupWizard(QWizard):
    """First-Run-Wizard. accept() schreibt den Marker NUR bei
    Total-Erfolg (alle 3 Steps green).
    """

    def __init__(
        self,
        whisper_target: Path,
        ollama_installer: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kira - Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.NoCancelButtonOnLastPage, True)

        # Light-theme-Override fuer Win11-Dark-Mode-Konsistenz mit anderen
        # Kira-Dialogen (Settings/About/Welcome).
        apply_light_theme(self)

        self.setMinimumSize(640, 480)

        self.addPage(WelcomePage(self))
        self.addPage(DownloadPage(whisper_target, ollama_installer, self))
        self.addPage(FinishedPage(self))

    def accept(self) -> None:  # noqa: N802 - Qt override
        """Marker NUR bei Total-Erfolg (User clickt Finish auf der letzten
        Page = alle 3 Pages durchlaufen, FinishedPage.isComplete() == True
        per default). Marker setzt Kira "konfiguriert", sodass der naechste
        Start den Wizard skippt.
        """
        try:
            mark_first_run_complete()
        except Exception:
            log.exception("mark_first_run_complete failed in accept()")
            # Trotzdem accept() durchlassen — der User soll Kira benutzen
            # koennen. Wenn der Marker beim naechsten Start fehlt, zeigt
            # Kira den Wizard halt nochmal — keine Daten verloren.
        super().accept()
