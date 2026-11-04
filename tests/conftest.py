from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Keep device tokens, session keys and logs out of the real ~/.amy and logs/."""
    monkeypatch.setenv("AMY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AMY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("AMY_LOG_FILE", "0")
    monkeypatch.setenv("AMY_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("AMY_HISTORY", "0")
    monkeypatch.setenv("PYHIVE_HOME", str(tmp_path / "pyhive"))
