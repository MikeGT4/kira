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
    GemmaPullWorker,
    OllamaSetupWorker,
    WhisperDownloadWorker,
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
    assert DEFAULT_GEMMA_TAG == "gemma3:12b"


# ---------------------------------------------------------------------------
# Helper: is_ollama_installed()
# ---------------------------------------------------------------------------

def test_is_ollama_installed_true_when_which_returns_path(mocker):
    mocker.patch(
        "kira.setup_wizard.shutil.which",
        return_value="C:\\Users\\Mike\\AppData\\Local\\Programs\\Ollama\\ollama.exe",
    )
    assert is_ollama_installed() is True


def test_is_ollama_installed_false_when_which_returns_none(mocker):
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
    assert kwargs["resume_download"] is True
    # Symlinks auf Win11 brauchen Admin oder Dev-Mode — wir wollen
    # echte Files im Cache, sonst bricht der erste F8-Press wenn
    # huggingface_hub zur Laufzeit Symlinks erwartet aber keine vorliegen.
    assert kwargs.get("local_dir_use_symlinks") is False

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
    fake_run = mocker.patch(
        "kira.setup_wizard.subprocess.run",
        return_value=MagicMock(returncode=0),
    )
    # time.sleep ueber-mocken damit der Wait-Loop nicht echt schlaeft
    mocker.patch("kira.setup_wizard.time.sleep", return_value=None)

    worker = OllamaSetupWorker(installer_path=installer)
    finished_calls: list[None] = []
    errors: list[str] = []
    worker.finished.connect(lambda: finished_calls.append(None))
    worker.error.connect(lambda msg: errors.append(msg))

    worker.run()

    fake_run.assert_called_once()
    args, kwargs = fake_run.call_args
    cmd = args[0] if args else kwargs.get("args")
    assert isinstance(cmd, list), "subprocess.run muss list-args bekommen, kein Shell-String"
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
    fake_run = mocker.patch("kira.setup_wizard.subprocess.run")

    worker = OllamaSetupWorker(installer_path=installer)
    errors: list[str] = []
    worker.error.connect(lambda msg: errors.append(msg))

    worker.run()

    fake_run.assert_not_called()
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# GemmaPullWorker
# ---------------------------------------------------------------------------

def test_gemma_worker_skips_pull_when_tag_in_list(qtbot, mocker):
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
