"""Tests for kira.setup_wizard — Workers + Helpers.

UI pages (QWizardPage subclasses) are smoke-tested only — full UI flow is
covered manually via the first-run experience in dev. Worker-Threads sind
durch direkten run()-Aufruf testbar (synchron) — wir spinnen keinen
QEventLoop, dafuer mocken wir alle externen Calls (huggingface_hub,
subprocess, urllib.request).

Mock-Strategie:
- huggingface_hub.snapshot_download via patch
- subprocess.run / subprocess.Popen via patch
- urllib.request.urlopen via patch (Mike's Codebase nutzt durchgehend
  urllib statt requests, siehe kira.updater)
- shutil.which via patch
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

if sys.platform != "win32":
    pytest.skip("setup_wizard module is Windows-only", allow_module_level=True)

from kira.setup_wizard import (
    DEFAULT_GEMMA_TAG,
    DEFAULT_WHISPER_REPO,
    OLLAMA_API_URL,
    WHISPER_ALLOWED_FILES,
    GemmaPullWorker,
    OllamaSetupWorker,
    WhisperDownloadWorker,
    _has_model_tag,
    is_ollama_installed,
    is_ollama_reachable,
)


# ---------------------------------------------------------------------------
# Module-level constants — sanity checks (Phase C3 spec-locks)
# ---------------------------------------------------------------------------

def test_ollama_api_url_uses_ipv4_loopback():
    """Win11 24H2+ resolved 'localhost' to IPv6 ::1, but Ollama bindet an
    IPv4 0.0.0.0:11434. localhost-URL gibt ConnectionRefused — daher
    HART 127.0.0.1.
    """
    assert OLLAMA_API_URL == "http://127.0.0.1:11434/api/tags"
    assert "localhost" not in OLLAMA_API_URL


def test_default_whisper_repo_is_large_v3_no_turbo():
    """Bundle-Default v0.1+ ist NON-turbo (German benchmark Mike 2026-04 —
    turbo schwaecher bei Fachvokabular). KEIN Drift gegen Bundle-Default.
    """
    assert DEFAULT_WHISPER_REPO == "Systran/faster-whisper-large-v3"


def test_default_gemma_tag():
    assert DEFAULT_GEMMA_TAG == "gemma4:12b"


# ---------------------------------------------------------------------------
# Helper: is_ollama_installed()
# ---------------------------------------------------------------------------

def test_is_ollama_installed_true_when_which_returns_path(mocker):
    mocker.patch(
        "kira.setup_wizard.shutil.which",
        return_value="C:\\Users\\Mike\\AppData\\Local\\Programs\\Ollama\\ollama.exe",
    )
    assert is_ollama_installed() is True


def test_is_ollama_installed_false_when_which_returns_none(mocker, monkeypatch):
    # find_ollama_exe checkt zuerst LOCALAPPDATA + PROGRAMFILES, dann PATH.
    # Alle drei muessen leer sein damit is_ollama_installed False returnt.
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    mocker.patch("kira.setup_wizard.shutil.which", return_value=None)
    assert is_ollama_installed() is False


# ---------------------------------------------------------------------------
# Helper: is_ollama_reachable()
# ---------------------------------------------------------------------------

def test_is_ollama_reachable_true_on_http_200(mocker):
    fake_response = MagicMock()
    fake_response.__enter__ = MagicMock(return_value=fake_response)
    fake_response.__exit__ = MagicMock(return_value=False)
    fake_response.status = 200
    mocker.patch("kira.setup_wizard.urllib.request.urlopen", return_value=fake_response)
    assert is_ollama_reachable() is True


def test_is_ollama_reachable_false_on_timeout(mocker):
    import socket
    mocker.patch("kira.setup_wizard.urllib.request.urlopen",
                 side_effect=socket.timeout("timed out"))
    assert is_ollama_reachable(timeout=0.1) is False


def test_is_ollama_reachable_false_on_connection_refused(mocker):
    mocker.patch("kira.setup_wizard.urllib.request.urlopen",
                 side_effect=ConnectionRefusedError())
    assert is_ollama_reachable(timeout=0.1) is False


def test_is_ollama_reachable_false_on_urlerror(mocker):
    import urllib.error
    mocker.patch("kira.setup_wizard.urllib.request.urlopen",
                 side_effect=urllib.error.URLError("boom"))
    assert is_ollama_reachable(timeout=0.1) is False


# ---------------------------------------------------------------------------
# WhisperDownloadWorker
# ---------------------------------------------------------------------------

def test_whisper_worker_calls_snapshot_download_with_resume(qtbot, tmp_path, mocker):
    target = tmp_path / "whisper-model"
    fake_download = mocker.patch(
        "kira.setup_wizard.snapshot_download",
        return_value=str(target),
    )
    worker = WhisperDownloadWorker(target_dir=target)

    finished_payloads: list[Path] = []
    worker.finished.connect(lambda p: finished_payloads.append(p))

    # Direct run() call (no thread) — synchron, wir wollen die Logik
    # testen, nicht das QThread-Scheduling.
    worker.run()

    fake_download.assert_called_once()
    kwargs = fake_download.call_args.kwargs
    assert kwargs["repo_id"] == DEFAULT_WHISPER_REPO
    assert Path(kwargs["local_dir"]) == target

    assert len(finished_payloads) == 1
    assert finished_payloads[0] == target


def test_whisper_worker_emits_error_on_network_failure(qtbot, tmp_path, mocker):
    target = tmp_path / "whisper-model"
    mocker.patch(
        "kira.setup_wizard.snapshot_download",
        side_effect=ConnectionError("DNS resolution failed"),
    )
    worker = WhisperDownloadWorker(target_dir=target)
    errors: list[str] = []
    worker.error.connect(lambda msg: errors.append(msg))

    worker.run()

    assert len(errors) == 1
    assert "DNS resolution failed" in errors[0] or "ConnectionError" in errors[0]


def test_whisper_worker_uses_custom_repo_id(qtbot, tmp_path, mocker):
    """Override-Pfad: User pinnt eigenes Repo via constructor-arg."""
    target = tmp_path / "whisper-model"
    fake_download = mocker.patch(
        "kira.setup_wizard.snapshot_download",
        return_value=str(target),
    )
    worker = WhisperDownloadWorker(
        target_dir=target,
        repo_id="Systran/faster-whisper-large-v3-turbo",
    )

    worker.run()

    kwargs = fake_download.call_args.kwargs
    assert kwargs["repo_id"] == "Systran/faster-whisper-large-v3-turbo"


# ---------------------------------------------------------------------------
# OllamaSetupWorker
# ---------------------------------------------------------------------------

def test_ollama_worker_skips_install_when_already_installed_and_reachable(
    qtbot, tmp_path, mocker,
):
    installer = tmp_path / "OllamaSetup.exe"
    installer.touch()
    mocker.patch("kira.setup_wizard.is_ollama_installed", return_value=True)
    mocker.patch("kira.setup_wizard.is_ollama_reachable", return_value=True)
    fake_run = mocker.patch("kira.setup_wizard.subprocess.run")

    worker = OllamaSetupWorker(installer_path=installer)
    finished_calls: list[None] = []
    worker.finished.connect(lambda: finished_calls.append(None))

    worker.run()

    fake_run.assert_not_called()
    assert len(finished_calls) == 1


def test_ollama_worker_runs_installer_when_not_installed(qtbot, tmp_path, mocker):
    installer = tmp_path / "OllamaSetup.exe"
    installer.touch()
    mocker.patch("kira.setup_wizard.is_ollama_installed", return_value=False)
    # Reachable check NACH Install muss True liefern (1 Call), sonst Loop
    mocker.patch("kira.setup_wizard.is_ollama_reachable",
                 side_effect=[False, True])
    # Cancel-Fix 2026-05-10: Installer laeuft jetzt via Popen statt run()
    # damit cancel() das Subprocess via terminate() killen kann.
    fake_proc = MagicMock()
    fake_proc.communicate.return_value = ("", "")
    fake_proc.returncode = 0
    fake_proc.poll.return_value = 0  # nicht mehr running
    fake_popen = mocker.patch(
        "kira.setup_wizard.subprocess.Popen",
        return_value=fake_proc,
    )
    # time.sleep ueber-mocken damit der Wait-Loop nicht echt schlaeft
    mocker.patch("kira.setup_wizard.time.sleep", return_value=None)

    worker = OllamaSetupWorker(installer_path=installer)
    finished_calls: list[None] = []
    errors: list[str] = []
    worker.finished.connect(lambda: finished_calls.append(None))
    worker.error.connect(lambda msg: errors.append(msg))

    worker.run()

    fake_popen.assert_called_once()
    args, kwargs = fake_popen.call_args
    cmd = args[0] if args else kwargs.get("args")
    assert isinstance(cmd, list), "subprocess.Popen muss list-args bekommen, kein Shell-String"
    assert str(installer) in cmd
    # Silent install flags — entweder /S oder /SILENT, beide gueltig
    assert any(flag in cmd for flag in ("/S", "/SILENT"))
    assert kwargs.get("shell") is not True  # NIEMALS shell=True
    assert errors == []
    assert len(finished_calls) == 1


def test_ollama_worker_emits_error_when_installer_path_missing(qtbot, tmp_path, mocker):
    """Pfad existiert nicht -> kein Call, sondern fail-fast Error."""
    installer = tmp_path / "missing.exe"
    mocker.patch("kira.setup_wizard.is_ollama_installed", return_value=False)
    mocker.patch("kira.setup_wizard.is_ollama_reachable", return_value=False)
    fake_popen = mocker.patch("kira.setup_wizard.subprocess.Popen")

    worker = OllamaSetupWorker(installer_path=installer)
    errors: list[str] = []
    worker.error.connect(lambda msg: errors.append(msg))

    worker.run()

    fake_popen.assert_not_called()
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# GemmaPullWorker
# ---------------------------------------------------------------------------

def test_gemma_worker_skips_pull_when_tag_in_list(qtbot, mocker):
    # find_ollama_exe gemockt → bare-name "ollama" (Test-default-fallback)
    mocker.patch("kira.setup_wizard.find_ollama_exe", return_value=None)
    fake_run = mocker.patch(
        "kira.setup_wizard.subprocess.run",
        return_value=MagicMock(
            returncode=0,
            stdout="NAME                ID    SIZE   MODIFIED\ngemma3:12b   abc   8.1 GB now\n",
            stderr="",
        ),
    )
    fake_popen = mocker.patch("kira.setup_wizard.subprocess.Popen")

    worker = GemmaPullWorker(model_tag="gemma3:12b")
    finished_calls: list[None] = []
    worker.finished.connect(lambda: finished_calls.append(None))

    worker.run()

    # ollama list wurde aufgerufen
    fake_run.assert_called_once()
    list_args = fake_run.call_args.args[0] if fake_run.call_args.args else fake_run.call_args.kwargs.get("args")
    assert list_args == ["ollama", "list"]
    # ollama pull wurde NICHT aufgerufen
    fake_popen.assert_not_called()
    assert len(finished_calls) == 1


def test_gemma_worker_pulls_when_tag_missing(qtbot, mocker):
    mocker.patch("kira.setup_wizard.find_ollama_exe", return_value=None)
    mocker.patch(
        "kira.setup_wizard.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="NAME ID SIZE\n", stderr=""),
    )
    # Popen mit Linebuffer fuer Progress
    fake_proc = MagicMock()
    fake_proc.stdout.__iter__ = lambda self: iter([
        "pulling manifest\n",
        "pulling abc123: 100%\n",
        "verifying sha256\n",
        "success\n",
    ])
    fake_proc.wait.return_value = 0
    fake_proc.returncode = 0
    fake_popen = mocker.patch(
        "kira.setup_wizard.subprocess.Popen",
        return_value=fake_proc,
    )

    worker = GemmaPullWorker(model_tag="gemma3:12b")
    progress_lines: list[str] = []
    finished_calls: list[None] = []
    worker.progress.connect(lambda line: progress_lines.append(line))
    worker.finished.connect(lambda: finished_calls.append(None))

    worker.run()

    fake_popen.assert_called_once()
    pull_args = fake_popen.call_args.args[0] if fake_popen.call_args.args else fake_popen.call_args.kwargs.get("args")
    assert pull_args == ["ollama", "pull", "gemma3:12b"]
    assert fake_popen.call_args.kwargs.get("shell") is not True
    # Progress-Signals geflossen
    assert len(progress_lines) >= 1
    assert len(finished_calls) == 1


def test_gemma_worker_emits_error_when_pull_returns_nonzero(qtbot, mocker):
    mocker.patch(
        "kira.setup_wizard.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="NAME\n", stderr=""),
    )
    fake_proc = MagicMock()
    fake_proc.stdout.__iter__ = lambda self: iter(["error: model not found\n"])
    fake_proc.wait.return_value = 1
    fake_proc.returncode = 1
    mocker.patch(
        "kira.setup_wizard.subprocess.Popen",
        return_value=fake_proc,
    )

    worker = GemmaPullWorker(model_tag="gemma3:99b")  # gibt's nicht
    errors: list[str] = []
    worker.error.connect(lambda msg: errors.append(msg))

    worker.run()

    assert len(errors) == 1


def test_gemma_worker_emits_error_when_ollama_list_fails(qtbot, mocker):
    """Ollama nicht gestartet -> list crasht -> Error, kein Pull."""
    import subprocess as real_sub
    mocker.patch(
        "kira.setup_wizard.subprocess.run",
        side_effect=real_sub.CalledProcessError(1, ["ollama", "list"]),
    )
    fake_popen = mocker.patch("kira.setup_wizard.subprocess.Popen")

    worker = GemmaPullWorker(model_tag="gemma3:12b")
    errors: list[str] = []
    worker.error.connect(lambda msg: errors.append(msg))

    worker.run()

    fake_popen.assert_not_called()
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# UI-Smoke-Tests (instantiation only — no real wizard run)
# ---------------------------------------------------------------------------

def test_setup_wizard_instantiates_with_three_pages(qtbot, tmp_path):
    from kira.setup_wizard import SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)

    # 3 Pages: Welcome (id 0), Download (id 1), Finished (id 2)
    assert len(wizard.pageIds()) == 3


def test_setup_wizard_accept_calls_mark_first_run_complete(qtbot, tmp_path, mocker):
    from kira.setup_wizard import SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    fake_mark = mocker.patch("kira.setup_wizard.mark_first_run_complete")

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)

    wizard.accept()

    fake_mark.assert_called_once()


def test_download_page_initially_not_complete(qtbot, tmp_path, mocker):
    """Bevor irgendein Worker fertig ist -> isComplete() == False, sonst
    kann der User auf 'Weiter' clicken bevor die Downloads durch sind.
    """
    from kira.setup_wizard import DownloadPage, SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    # Worker-Threads gar nicht erst starten
    mocker.patch.object(DownloadPage, "initializePage", return_value=None)

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)
    download_page = wizard.page(1)
    assert download_page.isComplete() is False


# ---------------------------------------------------------------------------
# Critical-Fix 2026-05-10: Cancel-Mechanismus + Cross-Worker-Abort
# ---------------------------------------------------------------------------

def _make_running_mock_worker():
    """Mock-Worker: isRunning() startet True, nach cancel()+wait() False.

    Simuliert den kooperativen Cancel-Pfad: cancel() laesst den Worker
    "abklingen", sodass der zweite isRunning()-Check (nach wait(2000))
    False zurueckgibt — also KEIN terminate()-Fallback noetig.
    """
    worker = MagicMock()
    # erst running, nach cancel+wait nicht mehr
    running_states = iter([True, False])

    def running():
        try:
            return next(running_states)
        except StopIteration:
            return False

    worker.isRunning.side_effect = running
    return worker


def test_cleanup_page_stops_running_workers(qtbot, tmp_path, mocker):
    """cleanupPage() ruft cancel() auf alle laufenden Worker und faellt
    auf terminate() zurueck wenn ein Worker nach wait(2000) noch laeuft.
    """
    from kira.setup_wizard import DownloadPage, SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    mocker.patch.object(DownloadPage, "initializePage", return_value=None)

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)
    download_page = wizard.page(1)

    # Drei Mock-Worker: zwei kooperativ (Whisper, Ollama), einer
    # unkooperativ (Gemma) -> braucht terminate-Fallback.
    whisper = _make_running_mock_worker()
    ollama = _make_running_mock_worker()
    # gemma: bleibt running auch nach cancel + wait(2s) -> terminate()
    gemma = MagicMock()
    gemma.isRunning.return_value = True

    download_page._whisper_worker = whisper
    download_page._ollama_worker = ollama
    download_page._gemma_worker = gemma

    download_page.cleanupPage()

    whisper.cancel.assert_called_once()
    whisper.wait.assert_called_with(2000)
    whisper.terminate.assert_not_called()

    ollama.cancel.assert_called_once()
    ollama.wait.assert_called_with(2000)
    ollama.terminate.assert_not_called()

    gemma.cancel.assert_called_once()
    # erst wait(2000), dann terminate() + wait(5000)
    gemma.terminate.assert_called_once()
    # Pruefen dass beide wait-Calls passierten:
    wait_calls = [c.args for c in gemma.wait.call_args_list]
    assert (2000,) in wait_calls
    assert (5000,) in wait_calls


def test_whisper_error_aborts_pipeline(qtbot, tmp_path, mocker):
    """Whisper-Error feuert: gemma_worker wird NIE gestartet, auch wenn
    Ollama danach noch normal finished feuert.
    """
    from kira.setup_wizard import DownloadPage, SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    mocker.patch.object(DownloadPage, "initializePage", return_value=None)
    # GemmaPullWorker-Constructor patchen - wir wollen sehen ob er
    # ueberhaupt instanziert wird.
    fake_gemma_cls = mocker.patch("kira.setup_wizard.GemmaPullWorker")

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)
    download_page = wizard.page(1)

    # Whisper-Error feuert ZUERST
    download_page._on_whisper_error("DNS resolution failed")

    # _pipeline_aborted ist gesetzt
    assert download_page._pipeline_aborted is True

    # Jetzt feuert _on_ollama_finished (Race: Ollama-Install war
    # parallel und hat fertig bevor _stop_all_workers wirken konnte)
    download_page._on_ollama_finished()

    # Gemma-Worker NIE instanziert
    fake_gemma_cls.assert_not_called()


def test_ollama_error_aborts_pipeline(qtbot, tmp_path, mocker):
    """Ollama-Error: gemma_worker NIE gestartet, _start_gemma early-return.
    """
    from kira.setup_wizard import DownloadPage, SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    mocker.patch.object(DownloadPage, "initializePage", return_value=None)
    fake_gemma_cls = mocker.patch("kira.setup_wizard.GemmaPullWorker")

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)
    download_page = wizard.page(1)

    download_page._on_ollama_error("Installer Exit-Code 1")

    assert download_page._pipeline_aborted is True

    # Auch wenn jetzt _start_gemma direkt gerufen wird (defensiv) ->
    # early-return, kein Pull.
    download_page._start_gemma()

    fake_gemma_cls.assert_not_called()


def test_setup_wizard_accept_warns_on_marker_failure(qtbot, tmp_path, mocker):
    """mark_first_run_complete wirft OSError -> QMessageBox.warning,
    aber super().accept() wird trotzdem aufgerufen damit Wizard schliesst.
    """
    from kira.setup_wizard import SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    mocker.patch(
        "kira.setup_wizard.mark_first_run_complete",
        side_effect=PermissionError("APPDATA-Ordner ist read-only"),
    )
    fake_warn = mocker.patch("kira.setup_wizard.QMessageBox.warning")

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)

    wizard.accept()

    # Warning angezeigt
    fake_warn.assert_called_once()
    # Title + Body deutsch + erwaehnt %APPDATA%\Kira
    args = fake_warn.call_args.args
    title_or_body = " ".join(str(a) for a in args)
    assert "Setup-Marker" in title_or_body
    assert "%APPDATA%" in title_or_body or "APPDATA" in title_or_body
    # Wizard schliesst (super().accept()) -> result == Accepted
    assert wizard.result() == int(SetupWizard.DialogCode.Accepted)


def test_setup_wizard_accept_does_not_swallow_keyboard_interrupt(qtbot, tmp_path, mocker):
    """KeyboardInterrupt darf NICHT vom OSError-Handler geschluckt werden —
    Mike's Ctrl+C / Quit muss durchkommen.
    """
    from kira.setup_wizard import SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    mocker.patch(
        "kira.setup_wizard.mark_first_run_complete",
        side_effect=KeyboardInterrupt(),
    )
    fake_warn = mocker.patch("kira.setup_wizard.QMessageBox.warning")

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)

    with pytest.raises(KeyboardInterrupt):
        wizard.accept()

    # KEINE Warning gezeigt
    fake_warn.assert_not_called()


# ---------------------------------------------------------------------------
# Phase F (2026-05-10): Hardening — Whitelist, mkdir-Race, Tag-Match,
# Lock-Race, closeEvent, RuntimeError-defense
# ---------------------------------------------------------------------------

def test_whisper_worker_passes_allow_patterns_whitelist(qtbot, tmp_path, mocker):
    """F1: snapshot_download muss mit allow_patterns gerufen werden, sonst
    koennten kompromittierte HF-Repos andere Files (Notebooks, .py) on-disk
    legen.
    """
    target = tmp_path / "whisper-model"
    fake_download = mocker.patch(
        "kira.setup_wizard.snapshot_download",
        return_value=str(target),
    )
    worker = WhisperDownloadWorker(target_dir=target)

    worker.run()

    fake_download.assert_called_once()
    kwargs = fake_download.call_args.kwargs
    assert "allow_patterns" in kwargs, \
        "snapshot_download muss allow_patterns kriegen (defense gegen rogue files in repo)"
    patterns = kwargs["allow_patterns"]
    # Liste, nicht None/leer/string
    assert isinstance(patterns, list), "allow_patterns muss list sein"
    assert len(patterns) > 0
    # Erwartete CTranslate2-Files dabei
    assert "model.bin" in patterns
    assert "config.json" in patterns
    assert "tokenizer.json" in patterns
    # Keine Wildcards die zu viel matchen ('*' alleine)
    assert "*" not in patterns


def test_whisper_allowed_files_constant_locked():
    """F1: Tuple-Form ist Module-Constant, falls jemand spaeter die Liste
    aendert, soll der Test laut werden — dafuer ist sie da.
    """
    assert WHISPER_ALLOWED_FILES == (
        "model.bin",
        "config.json",
        "tokenizer.json",
        "vocabulary.json",
        "preprocessor_config.json",
        "*.txt",
    )


def test_whisper_worker_emits_error_when_mkdir_fails(qtbot, tmp_path, mocker):
    """F5: mkdir wirft OSError (Disk-Full, ReadOnly-FS) — error-Signal
    statt silent-stirb.
    """
    target = tmp_path / "whisper-model"
    fake_download = mocker.patch("kira.setup_wizard.snapshot_download")
    mocker.patch.object(
        Path,
        "mkdir",
        side_effect=PermissionError("ReadOnly Filesystem"),
    )

    worker = WhisperDownloadWorker(target_dir=target)
    errors: list[str] = []
    worker.error.connect(lambda msg: errors.append(msg))

    worker.run()

    # snapshot_download niemals gerufen
    fake_download.assert_not_called()
    # error-Signal mit aussagekraeftiger Message
    assert len(errors) == 1
    assert "Whisper-Verzeichnis" in errors[0]
    assert "PermissionError" in errors[0] or "ReadOnly" in errors[0]


def test_has_model_tag_exact_match_only():
    """F6: gemma3:12b vs gemma3:12b-instruct — Substring-Match wuerde
    True liefern, exact-match auf erste Spalte muss aber False geben.
    """
    stdout = (
        "NAME                ID    SIZE   MODIFIED\n"
        "gemma3:12b-instruct abc   8.1 GB now\n"
    )
    # Such-Tag gemma3:12b ist NICHT als exact-Match in der NAME-Spalte
    assert _has_model_tag(stdout, "gemma3:12b") is False
    # Aber gemma3:12b-instruct schon
    assert _has_model_tag(stdout, "gemma3:12b-instruct") is True


def test_has_model_tag_finds_exact_tag():
    """F6: positive Pfad — exakter Tag in der NAME-Spalte matched."""
    stdout = (
        "NAME                ID    SIZE   MODIFIED\n"
        "gemma3:12b          abc   8.1 GB now\n"
        "llama3:8b           xyz   4.7 GB last week\n"
    )
    assert _has_model_tag(stdout, "gemma3:12b") is True
    assert _has_model_tag(stdout, "llama3:8b") is True
    assert _has_model_tag(stdout, "phi3:14b") is False


def test_has_model_tag_handles_empty_lines():
    """F6: leere Lines / Header-only / blanks duerfen den Helper nicht
    crashen lassen.
    """
    assert _has_model_tag("", "gemma3:12b") is False
    assert _has_model_tag("\n\n\n", "gemma3:12b") is False
    assert _has_model_tag("NAME ID SIZE\n", "gemma3:12b") is False


def test_gemma_worker_does_not_match_substring(qtbot, mocker):
    """F6 Integration: Worker sieht gemma3:12b-instruct in der Liste,
    fragt aber nach gemma3:12b — muss pull triggern, NICHT skip.
    """
    mocker.patch(
        "kira.setup_wizard.subprocess.run",
        return_value=MagicMock(
            returncode=0,
            stdout=(
                "NAME                ID    SIZE   MODIFIED\n"
                "gemma3:12b-instruct abc   8.1 GB now\n"
            ),
            stderr="",
        ),
    )
    fake_proc = MagicMock()
    fake_proc.stdout.__iter__ = lambda self: iter(["pulling: 100%\n"])
    fake_proc.wait.return_value = 0
    fake_proc.returncode = 0
    fake_popen = mocker.patch(
        "kira.setup_wizard.subprocess.Popen",
        return_value=fake_proc,
    )

    worker = GemmaPullWorker(model_tag="gemma3:12b")
    worker.run()

    # pull WURDE getriggert, weil exact-match auf gemma3:12b False war
    fake_popen.assert_called_once()


def test_abort_pipeline_idempotent_under_race(qtbot, tmp_path, mocker):
    """F7: Lock-protected idempotency — zwei parallele Errors duerfen
    NICHT zweimal _stop_all_workers() rufen (das kann QThread.terminate()
    in inkonsistenten State stuerzen).
    """
    from kira.setup_wizard import DownloadPage, SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    mocker.patch.object(DownloadPage, "initializePage", return_value=None)

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)
    download_page = wizard.page(1)

    # _stop_all_workers patchen damit wir die Call-Count messen
    spy_stop = mocker.patch.object(download_page, "_stop_all_workers")

    # Erster Call setzt Flag und ruft _stop_all_workers
    download_page._abort_pipeline()
    # Zweiter Call (Race-Sim) — Flag schon gesetzt, _stop nicht nochmal
    download_page._abort_pipeline()
    # Dritter Call ebenfalls no-op
    download_page._abort_pipeline()

    assert download_page._pipeline_aborted is True
    # Genau EIN Call zu _stop_all_workers — Lock haelt second/third zurueck
    assert spy_stop.call_count == 1


def test_close_event_cleans_up_running_workers(qtbot, tmp_path, mocker):
    """F9: closeEvent (X-Button, Alt+F4) muss cleanupPage auf der
    DownloadPage triggern, sonst laufen Worker im Hintergrund weiter
    (3 GB Whisper-Download niemand verfolgt).
    """
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QCloseEvent
    from kira.setup_wizard import DownloadPage, SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    mocker.patch.object(DownloadPage, "initializePage", return_value=None)

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)
    download_page = wizard.page(1)

    spy_cleanup = mocker.patch.object(download_page, "cleanupPage")

    # closeEvent braucht echtes QCloseEvent (PyQt akzeptiert kein
    # MagicMock — interner C++-Type-Check)
    real_event = QCloseEvent()
    wizard.closeEvent(real_event)

    spy_cleanup.assert_called_once()


def test_setup_wizard_accept_handles_runtime_error_too(qtbot, tmp_path, mocker):
    """F4: RuntimeError aus mark_first_run_complete (defensiv) muss vom
    accept-Handler genauso aufgefangen werden wie OSError. Schuetzt
    falls jemand spaeter firstrun.py wieder zu RuntimeError zurueck-
    driftet.
    """
    from kira.setup_wizard import SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    mocker.patch(
        "kira.setup_wizard.mark_first_run_complete",
        side_effect=RuntimeError("legacy bug"),
    )
    fake_warn = mocker.patch("kira.setup_wizard.QMessageBox.warning")

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)

    # Kein RuntimeError nach aussen
    wizard.accept()

    fake_warn.assert_called_once()


def test_append_log_escapes_html(qtbot, tmp_path, mocker):
    """F10: ollama-Output kann '<' enthalten — _append_log muss das via
    html.escape sichern, sonst broken-HTML im QTextEdit.
    """
    from kira.setup_wizard import DownloadPage, SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    mocker.patch.object(DownloadPage, "initializePage", return_value=None)

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)
    download_page = wizard.page(1)

    download_page._append_log("<script>alert(1)</script>")

    log_text = download_page._log.toPlainText()
    # toPlainText liefert escaped Text als Plain — < und > kommen rueber,
    # aber das Markup wird nicht als HTML gerendert. Die Garantie ist
    # dass der Render-Path den Text NICHT als script-Tag interpretiert.
    # Der escapete Text ist im Document, also < kommt wieder raus.
    assert "<script>" in log_text or "&lt;script&gt;" in download_page._log.toHtml()


def test_log_buffer_capped_at_500_blocks(qtbot, tmp_path, mocker):
    """F10: setMaximumBlockCount(500) — Gemma-Pull schreibt 80k+ Lines,
    ohne Cap waechst der QTextEdit-Buffer unbegrenzt.
    """
    from kira.setup_wizard import DownloadPage, SetupWizard

    whisper_target = tmp_path / "whisper"
    ollama_setup = tmp_path / "OllamaSetup.exe"
    ollama_setup.touch()

    mocker.patch.object(DownloadPage, "initializePage", return_value=None)

    wizard = SetupWizard(
        whisper_target=whisper_target,
        ollama_installer=ollama_setup,
    )
    qtbot.addWidget(wizard)
    download_page = wizard.page(1)

    assert download_page._log.document().maximumBlockCount() == 500
