"""``amy doctor`` — say plainly what works and what does not, instead of guessing from logs."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    hint: str = ""


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _load_yaml(path: str) -> Dict[str, Any]:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def llm_base_url(cfg: Dict[str, Any]) -> str:
    env = (os.environ.get("PYHIVE_LLM_BASE_URL") or "").strip()
    if env:
        return env
    ep = ((cfg.get("model") or {}).get("endpoint") or {}) if isinstance(cfg, dict) else {}
    mode = str(ep.get("mode") or "local").lower()
    if mode == "url" and ep.get("base_url"):
        return str(ep["base_url"])
    if mode == "ssh":
        port = int((ep.get("ssh") or {}).get("local_port") or 11435)
        return f"http://127.0.0.1:{port}/v1"
    if ep.get("base_url"):
        return str(ep["base_url"])
    return f"http://{ep.get('host') or '127.0.0.1'}:{int(ep.get('port') or 11434)}/v1"


def _probe_llm(base: str, timeout: float) -> Check:
    root = base.rstrip("/")
    root = root[:-3] if root.endswith("/v1") else root
    last = ""
    for path in ("/api/tags", "/v1/models"):
        try:
            with urllib.request.urlopen(root + path, timeout=timeout) as resp:
                body = json.loads(resp.read(200_000) or b"{}")
            models = body.get("models") or body.get("data") or []
            return Check("llm endpoint", OK, f"{root} ({len(models)} models)")
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = str(getattr(e, "reason", e))
    return Check(
        "llm endpoint",
        FAIL,
        f"{root} unreachable: {last}",
        "Start Ollama, or the SSH tunnel when model.endpoint.mode is ssh",
    )


def static_checks(*, probe_network: bool = True, timeout: float = 2.0) -> List[Check]:
    out: List[Check] = []
    v = sys.version_info
    if v < (3, 11):
        out.append(Check("python", FAIL, sys.version.split()[0], "Amy needs Python 3.11+"))
    elif v >= (3, 13):
        out.append(
            Check(
                "python",
                WARN,
                sys.version.split()[0],
                "Audio/ML wheels (faster-whisper, ctranslate2) are most reliable on 3.11/3.12",
            )
        )
    else:
        out.append(Check("python", OK, sys.version.split()[0]))

    home = os.environ.get("PYHIVE_HOME") or ""
    out.append(
        Check("PYHIVE_HOME", OK, home)
        if home and Path(home).is_dir()
        else Check("PYHIVE_HOME", FAIL, home or "unset", "Run via `amy` so apply_env sets it")
    )

    cfg: Dict[str, Any] = {}
    cfg_path = os.environ.get("HIVE_CONFIG") or ""
    if cfg_path and Path(cfg_path).is_file():
        try:
            cfg = _load_yaml(cfg_path)
            out.append(Check("hive config", OK, cfg_path))
        except Exception as e:
            out.append(Check("hive config", FAIL, f"{cfg_path}: {e}", "Fix the YAML syntax"))
    else:
        out.append(Check("hive config", FAIL, cfg_path or "unset"))

    out.append(
        Check("pyhive", OK, "importable")
        if _has("pyhive")
        else Check("pyhive", FAIL, "not importable", "Install PyHive into this environment")
    )

    try:
        from amy.guard import load_guard_config

        g = load_guard_config()
        if not g.enabled:
            out.append(Check("safety guard", FAIL, "disabled", "Set amy.guard.enabled: true"))
        else:
            detail = f"mode={g.mode} lockdown={g.lockdown} shell={g.allow_shell}"
            out.append(Check("safety guard", OK, detail))
    except Exception as e:
        out.append(Check("safety guard", FAIL, str(e)))

    out.append(
        Check("speech-to-text", OK, "faster_whisper")
        if _has("faster_whisper")
        else Check("speech-to-text", FAIL, "faster_whisper missing", "pip install faster-whisper")
    )
    out.append(
        Check("tts playback", OK, shutil.which("ffplay") or "")
        if shutil.which("ffplay")
        else Check("tts playback", WARN, "ffplay not on PATH", "Install FFmpeg and add it to PATH")
    )

    if _has("sounddevice"):
        try:
            import sounddevice as sd

            dev = sd.query_devices(kind="input")
            out.append(Check("microphone", OK, str(dev.get("name", "default"))))
        except Exception as e:
            out.append(Check("microphone", FAIL, str(e), "Plug in / enable a microphone"))
    else:
        out.append(Check("microphone", WARN, "sounddevice not installed"))

    root = Path(os.environ.get("AMY_ROOT") or Path(__file__).resolve().parents[1])
    dist = root / "apps" / "web" / "dist" / "index.html"
    out.append(
        Check("web HUD", OK, "built")
        if dist.is_file()
        else Check("web HUD", WARN, "not built", "cd apps/web && npm install && npm run build")
    )

    try:
        from amy.logs import log_dir

        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        out.append(Check("log dir", OK, str(d)))
    except OSError as e:
        out.append(Check("log dir", FAIL, str(e)))

    if probe_network:
        out.append(_probe_llm(llm_base_url(cfg), timeout))
    return out


def runtime_checks(host: Any) -> List[Check]:
    """Live state of a running host (used by ``/api/doctor``)."""
    out: List[Check] = []
    started = bool(getattr(host, "_started", False))
    out.append(Check("host", OK if started else WARN, "running" if started else "starting"))
    out.append(
        Check("voice", OK if getattr(host, "voice_ok", False) else FAIL, "")
        if started
        else Check("voice", WARN, "host still starting")
    )
    out.append(
        Check("wake word", OK if getattr(host, "wake_ok", False) else FAIL, "")
        if started
        else Check("wake word", WARN, "host still starting")
    )
    guard = getattr(host, "guard", None)
    if guard is None:
        out.append(Check("guard runtime", WARN if not started else FAIL, "not installed"))
    else:
        st = guard.status()
        out.append(Check("guard runtime", OK, f"mode={st.get('mode')} lockdown={st.get('lockdown')}"))
    bus = getattr(host, "bus", None)
    if bus is not None:
        out.append(Check("tools", OK, f"{len(bus.snapshot().tools)} exposed"))
        out.append(Check("live clients", OK, str(getattr(bus, "watcher_count", 0))))
    return out


def summarize(checks: List[Check]) -> Dict[str, Any]:
    worst = FAIL if any(c.status == FAIL for c in checks) else WARN if any(c.status == WARN for c in checks) else OK
    return {"ok": worst != FAIL, "status": worst, "checks": [asdict(c) for c in checks]}


def run_cli(*, as_json: bool = False, probe_network: bool = True, echo: Optional[Callable[[str], None]] = None) -> int:
    echo = echo or print
    checks = static_checks(probe_network=probe_network)
    report = summarize(checks)
    if as_json:
        echo(json.dumps(report, indent=2))
    else:
        mark = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}
        for c in checks:
            line = f"{mark[c.status]} {c.name:<16} {c.detail}"
            echo(line.rstrip())
            if c.hint and c.status != OK:
                echo(f"       -> {c.hint}")
        echo("")
        echo({OK: "All good.", WARN: "Usable, with warnings.", FAIL: "Some checks failed."}[report["status"]])
    return 0 if report["ok"] else 1
