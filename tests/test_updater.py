"""Tests for kira.updater. All HTTP is mocked."""
from __future__ import annotations
import io
import json
from unittest.mock import patch

import pytest

from kira.updater import (
    UpdateCheckResult,
    check_for_update,
    download_asset,
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
