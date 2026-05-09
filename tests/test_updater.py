"""Tests for kira.updater. All HTTP is mocked."""
from __future__ import annotations
import hashlib
import io
import json
from unittest.mock import patch

import pytest

from kira.updater import (
    ReleaseAsset,
    UpdateCheckResult,
    check_for_update,
    download_asset,
    download_bundle,
    verify_sha256sums,
)


def _mock_response(payload: dict):
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


@pytest.fixture
def fake_release():
    return {
        "tag_name": "v0.2.0",
        "assets": [
            {
                "name": "Kira-Setup-v0.2.0.exe",
                "browser_download_url": "https://example.com/Kira-Setup-v0.2.0.exe",
            }
        ],
    }


def test_check_returns_newer_when_remote_higher(fake_release):
    with patch("kira.updater.urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value = _mock_response(fake_release)
        result = check_for_update(local_version="0.1.0", repo="x/y")
    assert result.status == "newer"
    assert result.remote_version == "0.2.0"
    assert result.asset_url == "https://example.com/Kira-Setup-v0.2.0.exe"
    assert result.asset_name == "Kira-Setup-v0.2.0.exe"


def test_check_returns_current_when_versions_match(fake_release):
    fake_release["tag_name"] = "v0.1.0"
    with patch("kira.updater.urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value = _mock_response(fake_release)
        result = check_for_update(local_version="0.1.0", repo="x/y")
    assert result.status == "current"
    assert result.asset_url is None


def test_check_returns_local_newer_when_local_higher(fake_release):
    fake_release["tag_name"] = "v0.0.9"
    with patch("kira.updater.urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value = _mock_response(fake_release)
        result = check_for_update(local_version="0.1.0", repo="x/y")
    assert result.status == "local_newer"


def test_check_returns_no_asset_when_assets_missing(fake_release):
    fake_release["assets"] = [{"name": "source.zip", "browser_download_url": "x"}]
    with patch("kira.updater.urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value = _mock_response(fake_release)
        result = check_for_update(local_version="0.1.0", repo="x/y")
    assert result.status == "no_asset"


def test_check_returns_failed_on_network_error():
    with patch(
        "kira.updater.urllib.request.urlopen",
        side_effect=ConnectionError("offline"),
    ):
        result = check_for_update(local_version="0.1.0", repo="x/y")
    assert result.status == "failed"
    assert "offline" in (result.error or "")


def test_check_strips_v_prefix_from_tag(fake_release):
    fake_release["tag_name"] = "v1.0.0"
    with patch("kira.updater.urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value = _mock_response(fake_release)
        result = check_for_update(local_version="0.1.0", repo="x/y")
    assert result.remote_version == "1.0.0"


def test_check_handles_tag_without_v_prefix(fake_release):
    fake_release["tag_name"] = "0.3.0"
    with patch("kira.updater.urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value = _mock_response(fake_release)
        result = check_for_update(local_version="0.1.0", repo="x/y")
    assert result.remote_version == "0.3.0"
    assert result.status == "newer"


def test_check_picks_setup_exe_asset_among_multiple(fake_release):
    fake_release["assets"] = [
        {"name": "checksums.txt", "browser_download_url": "x"},
        {"name": "Kira-Setup-v0.2.0.exe", "browser_download_url": "y"},
        {"name": "source.zip", "browser_download_url": "z"},
    ]
    with patch("kira.updater.urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value = _mock_response(fake_release)
        result = check_for_update(local_version="0.1.0", repo="x/y")
    assert result.asset_url == "y"


def test_download_asset_writes_to_target_path(tmp_path):
    target = tmp_path / "Kira-Setup-v0.2.0.exe"
    fake_bytes = b"fake setup binary content"
    with patch("kira.updater.urllib.request.urlretrieve") as mock_retrieve:
        def fake_retrieve(url, filename):
            with open(filename, "wb") as f:
                f.write(fake_bytes)
            return filename, None
        mock_retrieve.side_effect = fake_retrieve
        path = download_asset("https://example.com/Kira-Setup-v0.2.0.exe", target)
    assert path == target
    assert target.read_bytes() == fake_bytes


# ===== Multi-Asset Bundle (v0.2) =====================================


@pytest.fixture
def fake_bundle_release():
    """Realistisches v0.2-Bundle-Release: 1 Stub + 7 .bin-Splits + SHA256SUMS."""
    return {
        "tag_name": "v0.2.0",
        "assets": [
            {
                "name": "Kira-Setup-v0.2.0.exe",
                "browser_download_url": "https://example.com/setup.exe",
                "size": 2_000_000,
            },
            {
                "name": "Kira-Setup-v0.2.0-1.bin",
                "browser_download_url": "https://example.com/1.bin",
                "size": 2_147_483_647,
            },
            {
                "name": "Kira-Setup-v0.2.0-2.bin",
                "browser_download_url": "https://example.com/2.bin",
                "size": 2_147_483_647,
            },
            {
                "name": "Kira-Setup-v0.2.0-7.bin",
                "browser_download_url": "https://example.com/7.bin",
                "size": 1_500_000_000,
            },
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": "https://example.com/sha256sums",
                "size": 1024,
            },
        ],
    }


def test_check_returns_full_bundle_on_newer(fake_bundle_release):
    with patch("kira.updater.urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value = _mock_response(fake_bundle_release)
        result = check_for_update(local_version="0.1.0", repo="x/y")
    assert result.status == "newer"
    # Backwards-compat: asset_url ist der Stub
    assert result.asset_name == "Kira-Setup-v0.2.0.exe"
    # Bundle hat ALLE 4 Bundle-Files (Stub + 3 Splits)
    assert len(result.bundle_assets) == 4
    # Stub MUSS erstes Element sein (Splits sind sekundaer)
    assert result.bundle_assets[0].name == "Kira-Setup-v0.2.0.exe"
    # Splits stabil sortiert nach Name -> 1.bin, 2.bin, 7.bin
    split_names = [a.name for a in result.bundle_assets[1:]]
    assert split_names == [
        "Kira-Setup-v0.2.0-1.bin",
        "Kira-Setup-v0.2.0-2.bin",
        "Kira-Setup-v0.2.0-7.bin",
    ]
    # SHA256SUMS-URL erkannt
    assert result.sha256sums_url == "https://example.com/sha256sums"


def test_check_bundle_with_no_sha256sums_returns_none(fake_bundle_release):
    """Wenn das Release keine SHA256SUMS.txt liefert, sha256sums_url=None
    statt zu crashen — Mike's v0.2-Build hat das erstmal noch nicht."""
    fake_bundle_release["assets"] = [
        a for a in fake_bundle_release["assets"]
        if a["name"] != "SHA256SUMS.txt"
    ]
    with patch("kira.updater.urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value = _mock_response(fake_bundle_release)
        result = check_for_update(local_version="0.1.0", repo="x/y")
    assert result.status == "newer"
    assert result.sha256sums_url is None
    # Bundle-Liste haelt trotzdem alle vier Bundle-Files
    assert len(result.bundle_assets) == 4


def test_download_bundle_writes_all_files_with_original_names(tmp_path):
    """Inno braucht alle Files mit Original-Namen im SELBEN Ordner."""
    assets = [
        ReleaseAsset(name="Kira-Setup-v0.2.0.exe", url="https://x/setup.exe"),
        ReleaseAsset(name="Kira-Setup-v0.2.0-1.bin", url="https://x/1.bin"),
        ReleaseAsset(name="Kira-Setup-v0.2.0-2.bin", url="https://x/2.bin"),
    ]
    fake_bytes = {a.name: f"fake-{a.name}".encode() for a in assets}

    def fake_retrieve(url, filename, reporthook=None):
        # Match URL → asset
        name = next(a.name for a in assets if a.url == url)
        with open(filename, "wb") as f:
            f.write(fake_bytes[name])
        if reporthook:
            reporthook(1, len(fake_bytes[name]), len(fake_bytes[name]))
        return filename, None

    progress_calls = []
    with patch("kira.updater.urllib.request.urlretrieve",
               side_effect=fake_retrieve):
        paths = download_bundle(
            assets, tmp_path,
            on_progress=lambda n, d, t: progress_calls.append((n, d, t)),
        )

    assert len(paths) == 3
    # Alle Files im SELBEN tmp_path-Verzeichnis
    assert all(p.parent == tmp_path for p in paths)
    # Originalnamen behalten
    assert {p.name for p in paths} == {
        "Kira-Setup-v0.2.0.exe",
        "Kira-Setup-v0.2.0-1.bin",
        "Kira-Setup-v0.2.0-2.bin",
    }
    # Inhalt OK
    for p in paths:
        assert p.read_bytes() == fake_bytes[p.name]
    # Progress wurde fuer jedes Asset gerufen
    assert {c[0] for c in progress_calls} == {a.name for a in assets}


def test_verify_sha256sums_passes_when_all_hashes_match(tmp_path):
    a = tmp_path / "fileA"
    b = tmp_path / "fileB"
    a.write_bytes(b"content-A")
    b.write_bytes(b"content-B")

    sums = (
        f"{hashlib.sha256(b'content-A').hexdigest()}  fileA\n"
        f"{hashlib.sha256(b'content-B').hexdigest()}  fileB\n"
    )
    sums_path = tmp_path / "SHA256SUMS.txt"
    sums_path.write_text(sums, encoding="utf-8")

    ok, errors = verify_sha256sums(sums_path, tmp_path)
    assert ok is True
    assert errors == []


def test_verify_sha256sums_fails_on_mismatch(tmp_path):
    a = tmp_path / "fileA"
    a.write_bytes(b"actual-content")
    sums = "0" * 64 + "  fileA\n"
    sums_path = tmp_path / "SHA256SUMS.txt"
    sums_path.write_text(sums, encoding="utf-8")

    ok, errors = verify_sha256sums(sums_path, tmp_path)
    assert ok is False
    assert any("mismatch" in e for e in errors)


def test_verify_sha256sums_fails_on_missing_file(tmp_path):
    sums = (
        f"{hashlib.sha256(b'x').hexdigest()}  notthere.bin\n"
    )
    sums_path = tmp_path / "SHA256SUMS.txt"
    sums_path.write_text(sums, encoding="utf-8")

    ok, errors = verify_sha256sums(sums_path, tmp_path)
    assert ok is False
    assert any("fehlt" in e for e in errors)


def test_verify_sha256sums_handles_binary_marker_asterisk(tmp_path):
    """GNU sha256sum's binary mode prepends '*' to filename. Our parser
    must strip it."""
    a = tmp_path / "fileA"
    a.write_bytes(b"content")
    sums = f"{hashlib.sha256(b'content').hexdigest()}  *fileA\n"
    sums_path = tmp_path / "SHA256SUMS.txt"
    sums_path.write_text(sums, encoding="utf-8")

    ok, errors = verify_sha256sums(sums_path, tmp_path)
    assert ok is True
    assert errors == []
