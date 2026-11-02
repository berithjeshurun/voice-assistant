"""Cross-platform env bootstrap for the Amy host."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .branding import ASSISTANT_NAME, DEFAULT_WAKE_PHRASE


def amy_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        # File fills gaps; process env wins.
        if key and key not in os.environ:
            os.environ[key] = val


def apply_env(*, home: Optional[str] = None, config: Optional[str] = None) -> Path:
    """Set PYHIVE_HOME / HIVE_CONFIG / assistant name. Returns Amy root."""
    root = amy_root()
    _load_dotenv(root / ".env")

    if home:
        os.environ["PYHIVE_HOME"] = str(Path(home).expanduser().resolve())
    elif not (os.environ.get("PYHIVE_HOME") or "").strip():
        # Prefer HiveSTEAM on Windows; fall back to ~/.pyhive elsewhere.
        candidate = Path("G:/HiveSTEAM")
        if candidate.is_dir():
            os.environ["PYHIVE_HOME"] = str(candidate.resolve())
        else:
            os.environ["PYHIVE_HOME"] = str((Path.home() / ".pyhive").resolve())

    cfg = config or os.environ.get("HIVE_CONFIG")
    if cfg:
        os.environ["HIVE_CONFIG"] = str(Path(cfg).expanduser().resolve())
    else:
        os.environ["HIVE_CONFIG"] = str((root / "config" / "hive.yaml").resolve())

    os.environ.setdefault("PYHIVE_ASSISTANT_NAME", ASSISTANT_NAME)
    os.environ.setdefault("AMY_ROOT", str(root))
    os.environ.setdefault("AMY_WAKE_PHRASE", DEFAULT_WAKE_PHRASE)
    if not (os.environ.get("HIVE_ARSENAL") or "").strip():
        arsenal = Path("H:/New_VLibs/v4")
        if arsenal.is_dir():
            os.environ["HIVE_ARSENAL"] = str(arsenal.resolve())

    Path(os.environ["PYHIVE_HOME"]).mkdir(parents=True, exist_ok=True)
    return root
