"""kira/__init__.py exposes the version and update repo constants."""
from __future__ import annotations
import re

import kira


def test_version_is_pep440_string():
    assert isinstance(kira.__version__, str)
    assert re.fullmatch(r"\d+\.\d+\.\d+", kira.__version__), kira.__version__


def test_version_matches_pyproject():
    """__version__ must equal the version field in pyproject.toml."""
    from pathlib import Path
    text = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match is not None, "pyproject.toml has no version line"
    assert kira.__version__ == match.group(1)


def test_update_repo_is_owner_slash_name():
    assert isinstance(kira.UPDATE_REPO, str)
    assert re.fullmatch(r"[\w.-]+/[\w.-]+", kira.UPDATE_REPO), kira.UPDATE_REPO
