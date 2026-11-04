import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """One offscreen QApplication. Qt allows a single application per process."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep tests off the project settings.json and _cases folder."""
    monkeypatch.setenv("TG51_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("TG51_CASES", str(tmp_path / "_cases"))
