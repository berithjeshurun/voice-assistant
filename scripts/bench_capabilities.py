"""Amy capability + latency benchmark suite.

Sections: infra, desktop, web, voice/ack, parallel tasks, E2E API.
Writes logs/capability_bench.json and prints a console scorecard.

Usage (from Amy root, with env loaded):
  .\\scripts\\_env.ps1; python scripts\\bench_capabilities.py
  python scripts\\bench_capabilities.py --skip-e2e
  python scripts\\bench_capabilities.py --skip-desktop
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import concurrent.futures
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "logs" / "capability_bench.json"
AMY_PORT = int(os.environ.get("AMY_PORT") or 8787)
BENCH_TOKEN = os.environ.get("AMY_BENCH_TOKEN") or "amy-bench-token"
VS_BASE = (os.environ.get("VOICESTUDIO_BASE_URL") or "http://127.0.0.1:3900").rstrip("/")
FRIDAY_VOICE = (
    os.environ.get("VOICESTUDIO_VOICE")
    or os.environ.get("AMY_TTS_VOICE")
    or "F.R.I.D.A.Y"
)


@dataclass
class Result:
    name: str
    section: str
    ok: bool
    ms: float = 0.0
    detail: str = ""
    skipped: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    t0 = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t0) * 1000.0


def _ok_tool(d: Any) -> bool:
    if not isinstance(d, dict):
        return False
    if d.get("ok") is True:
        return True
    if d.get("status") == "success":
        return True
    return False


def _json_get(url: str, *, timeout: float = 15.0, headers: Optional[Dict[str, str]] = None) -> Any:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8", errors="replace"))


def _json_post(
    url: str,
    body: Dict[str, Any],
    *,
    timeout: float = 120.0,
    headers: Optional[Dict[str, str]] = None,
) -> tuple[int, Any, bytes]:
    data = json.dumps(body).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                parsed = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
            except json.JSONDecodeError:
                parsed = {"raw": raw[:200]}
            return int(getattr(resp, "status", 200) or 200), parsed, raw
    except urllib.error.HTTPError as e:
        raw = e.read() if e.fp else b""
        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
        except Exception:
            parsed = {"error": str(e), "body": raw[:400].decode("utf-8", errors="replace")}
        return int(e.code), parsed, raw


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def section_infra(results: List[Result]) -> None:
    from amy.doctor import static_checks

    checks, ms = _timed(lambda: static_checks(probe_network=True, timeout=3.0))
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]
    results.append(
        Result(
            "doctor_static",
            "infra",
            ok=not fails,
            ms=ms,
            detail=f"ok={sum(1 for c in checks if c.status=='ok')} warn={len(warns)} fail={len(fails)}",
            meta={"checks": [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks]},
        )
    )

    for mod, label in (
        ("faster_whisper", "import_faster_whisper"),
        ("pynput", "import_pynput"),
        ("pyautogui", "import_pyautogui"),
    ):
        present = _has(mod)
        results.append(
            Result(
                label,
                "infra",
                ok=present if mod != "pyautogui" else True,
                skipped=(mod == "pyautogui" and not present),
                detail="present" if present else "missing (gap — Amy uses os_* tools, not pyautogui)",
                meta={"required_for_amy": mod != "pyautogui"},
            )
        )
    ff = shutil.which("ffplay") or shutil.which("ffplay.exe")
    results.append(
        Result("ffplay", "infra", ok=bool(ff), detail=str(ff or "not on PATH"))
    )

    # SSH tunnel + Ollama
    try:
        from pyhive.core.gateway.endpoint import SSHTunnelConfig, ensure_ssh_tunnel

        def _tunnel():
            ssh = SSHTunnelConfig(
                host="192.168.68.89",
                user="user",
                port=22,
                remote_host="127.0.0.1",
                remote_port=11434,
                local_port=11435,
                password=os.environ.get("PYHIVE_SSH_PASSWORD"),
            )
            return ensure_ssh_tunnel(ssh, wait_s=20)

        (_, label), ms = _timed(_tunnel)
        results.append(Result("ssh_tunnel", "infra", ok=True, ms=ms, detail=str(label)))
    except Exception as e:
        results.append(Result("ssh_tunnel", "infra", ok=_port_open("127.0.0.1", 11435), detail=str(e)[:200]))

    # qwen3 chat via native API
    def _llm_chat():
        from pyhive.core.gateway.gateway import llm_from_spec

        llm = llm_from_spec("qwen3:14b", raw=True, think=False)
        return llm.chat(
            [
                {"role": "system", "content": "Reply in one short sentence."},
                {"role": "user", "content": "Say ready in three words."},
            ],
            stream=False,
            max_tokens=32,
        )

    try:
        raw, ms = _timed(_llm_chat)
        content = (raw.get("content") or "") if isinstance(raw, dict) else ""
        thinking = (raw.get("thinking") or "") if isinstance(raw, dict) else ""
        results.append(
            Result(
                "llm_qwen3_chat",
                "infra",
                ok=bool(content.strip()) and not thinking.strip(),
                ms=ms,
                detail=repr(content[:120]),
                meta={"thinking_empty": not bool(thinking.strip())},
            )
        )
    except Exception as e:
        results.append(Result("llm_qwen3_chat", "infra", ok=False, detail=str(e)[:240]))

    # VoiceStudio
    def _vs_health():
        return _json_get(f"{VS_BASE}/health", timeout=8.0)

    try:
        body, ms = _timed(_vs_health)
        results.append(
            Result(
                "voicestudio_health",
                "infra",
                ok=True,
                ms=ms,
                detail=str(body)[:160],
            )
        )
    except Exception as e:
        # try start
        vs_exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "VoiceStudio" / "VoiceStudio.exe"
        if vs_exe.is_file():
            subprocess.Popen([str(vs_exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(8)
            try:
                body, ms = _timed(_vs_health)
                results.append(Result("voicestudio_health", "infra", ok=True, ms=ms, detail=f"started: {body}"[:160]))
            except Exception as e2:
                results.append(Result("voicestudio_health", "infra", ok=False, detail=str(e2)[:200]))
        else:
            results.append(Result("voicestudio_health", "infra", ok=False, detail=str(e)[:200]))

    def _friday_synth():
        payload = {
            "model": "omnivoice",
            "input": "Benchmark voice check.",
            "voice": FRIDAY_VOICE,
            "response_format": "mp3",
        }
        code, parsed, raw = _json_post(
            f"{VS_BASE}/v1/audio/speech",
            payload,
            timeout=180.0,
            headers={"Accept": "audio/mpeg, application/json, */*"},
        )
        # success = audio bytes (non-json) or 200
        return code, len(raw), parsed

    try:
        (code, nbytes, _), ms = _timed(_friday_synth)
        results.append(
            Result(
                "friday_tts_synth",
                "infra",
                ok=code == 200 and nbytes > 500,
                ms=ms,
                detail=f"http={code} bytes={nbytes} voice={FRIDAY_VOICE}",
            )
        )
    except Exception as e:
        results.append(Result("friday_tts_synth", "infra", ok=False, detail=str(e)[:240]))


def section_desktop(results: List[Result]) -> None:
    from amy.tools import os_controls as osc

    out, ms = _timed(lambda: osc.os_list_apps(query="notepad", limit=10))
    results.append(
        Result(
            "os_list_apps_notepad",
            "desktop",
            ok=_ok_tool(out),
            ms=ms,
            detail=str(out)[:180],
        )
    )

    out, ms = _timed(lambda: osc.os_open_app(name="notepad"))
    results.append(Result("os_open_app_notepad", "desktop", ok=_ok_tool(out), ms=ms, detail=str(out)[:180]))
    time.sleep(1.2)

    out, ms = _timed(lambda: osc.os_process_list(name="notepad", limit=10))
    procs = (out.get("processes") if isinstance(out, dict) else None) or []
    results.append(
        Result(
            "os_process_list_notepad",
            "desktop",
            ok=_ok_tool(out) and len(procs) >= 1,
            ms=ms,
            detail=f"count={len(procs)}",
        )
    )

    out, ms = _timed(lambda: osc.os_active_window())
    results.append(Result("os_active_window", "desktop", ok=_ok_tool(out), ms=ms, detail=str(out)[:180]))

    out, ms = _timed(lambda: osc.browse_url(url="https://example.com"))
    results.append(Result("browse_url_example", "desktop", ok=_ok_tool(out), ms=ms, detail=str(out)[:180]))

    # Brightness nudge + restore (soft-skip on external monitors)
    out1, ms1 = _timed(lambda: osc.os_brightness(delta=-1))
    if _ok_tool(out1):
        out2, ms2 = _timed(lambda: osc.os_brightness(delta=1))
        results.append(
            Result(
                "os_brightness_nudge_restore",
                "desktop",
                ok=_ok_tool(out2),
                ms=ms1 + ms2,
                detail=f"down={out1} up={out2}"[:200],
            )
        )
    else:
        results.append(
            Result(
                "os_brightness_nudge_restore",
                "desktop",
                ok=True,
                skipped=True,
                ms=ms1,
                detail=f"unavailable (external monitor?): {out1}"[:200],
            )
        )

    out, ms = _timed(lambda: osc.os_process_kill(name="notepad"))
    results.append(
        Result(
            "os_process_kill_notepad",
            "desktop",
            ok=_ok_tool(out),
            ms=ms,
            detail=str(out)[:180],
        )
    )


def section_web(results: List[Result]) -> None:
    from hivesteam.builtins import web as webmod

    async def _search():
        return await webmod.web_search("what is example.com", num=5, timeout=20)

    try:
        out, ms = _timed(lambda: asyncio.run(_search()))
        data = out.get("data") if isinstance(out, dict) else {}
        results_list = (data or {}).get("results") if isinstance(data, dict) else []
        digest = (data or {}).get("digest") if isinstance(data, dict) else ""
        ok = out.get("status") == "success" and (bool(results_list) or bool(digest))
        results.append(
            Result(
                "web_search",
                "web",
                ok=ok,
                ms=ms,
                detail=f"results={len(results_list or [])} digest_len={len(digest or '')}",
            )
        )
        url = "https://example.com"
        if results_list and isinstance(results_list[0], dict) and results_list[0].get("url"):
            url = str(results_list[0]["url"])
    except Exception as e:
        results.append(Result("web_search", "web", ok=False, detail=str(e)[:240]))
        url = "https://example.com"

    async def _fetch():
        return await webmod.web_fetch(url)

    try:
        out, ms = _timed(lambda: asyncio.run(_fetch()))
        ok = isinstance(out, dict) and out.get("status") == "success"
        results.append(Result("web_fetch", "web", ok=ok, ms=ms, detail=str(out)[:180]))
    except Exception as e:
        results.append(Result("web_fetch", "web", ok=False, detail=str(e)[:240]))


def section_voice(results: List[Result]) -> None:
    from pyhive.core.host.ack_aiml import reset_aiml_kernel
    from pyhive.core.host.ack_policy import reset_ack_policy
    from pyhive.core.host.progressive_ack import begin_turn

    reset_ack_policy()
    reset_aiml_kernel()
    goals = [
        "what is the weather in hyderabad",
        "search for quantum computing news",
        "turn down the brightness",
        "play some lo-fi music",
        "what time is it",
        "open chrome",
        "look up the capital of france",
        "check my calendar",
    ]
    lines: List[str] = []
    t0 = time.perf_counter()
    for g in goals:
        ack = begin_turn(g, llm=None, timeout_s=0.0, enabled=True)
        if ack.text:
            lines.append(ack.text)
    ms = (time.perf_counter() - t0) * 1000.0
    unique = len(set(lines))
    results.append(
        Result(
            "progressive_ack_variety",
            "voice",
            ok=len(lines) >= 6 and unique >= 3,
            ms=ms,
            detail=f"n={len(lines)} unique={unique}",
            meta={"samples": lines[:8]},
        )
    )

    # Piper ack TTS
    try:
        from hivesteam.external.service_vce import vce_tts

        out, ms = _timed(lambda: vce_tts(text="On it.", playback="none"))
        results.append(
            Result(
                "piper_ack_tts",
                "voice",
                ok=_ok_tool(out) or (isinstance(out, dict) and out.get("status") == "success"),
                ms=ms,
                detail=str(out)[:160],
            )
        )
    except Exception as e:
        results.append(Result("piper_ack_tts", "voice", ok=False, detail=str(e)[:200]))

    # Friday TTS (synth only — already timed in infra; play short for latency feel)
    try:
        from hivesteam.external.service_voicestudio import voicestudio_tts

        out, ms = _timed(
            lambda: voicestudio_tts(
                "Got it.",
                voice=FRIDAY_VOICE,
                playback="none",
                timeout=180.0,
            )
        )
        results.append(
            Result(
                "friday_tts_tool",
                "voice",
                ok=_ok_tool(out) or (isinstance(out, dict) and out.get("status") == "success"),
                ms=ms,
                detail=str(out.get("data") if isinstance(out, dict) else out)[:160],
            )
        )
    except Exception as e:
        results.append(Result("friday_tts_tool", "voice", ok=False, detail=str(e)[:200]))

    # LLM full reply latency
    try:
        from pyhive.core.gateway.gateway import llm_from_spec

        llm = llm_from_spec("qwen3:14b", raw=True, think=False)

        def _ask():
            return llm.chat(
                [{"role": "user", "content": "In one short sentence, what is 2+2?"}],
                stream=False,
                max_tokens=40,
            )

        raw, ms = _timed(_ask)
        content = (raw.get("content") or "") if isinstance(raw, dict) else ""
        results.append(
            Result(
                "llm_full_reply_latency",
                "voice",
                ok="4" in content or "four" in content.lower(),
                ms=ms,
                detail=repr(content[:120]),
            )
        )
    except Exception as e:
        results.append(Result("llm_full_reply_latency", "voice", ok=False, detail=str(e)[:200]))


def section_parallel(results: List[Result]) -> None:
    from hivesteam.builtins import web as webmod
    from pyhive.core.gateway.gateway import llm_from_spec

    from amy.tools import os_controls as osc

    def job_procs():
        t0 = time.perf_counter()
        out = osc.os_process_list(limit=15)
        return "procs", _ok_tool(out), (time.perf_counter() - t0) * 1000.0, out

    def job_search():
        t0 = time.perf_counter()
        out = asyncio.run(webmod.web_search("hyderabad weather", num=3, timeout=18))
        ok = isinstance(out, dict) and out.get("status") == "success"
        return "search", ok, (time.perf_counter() - t0) * 1000.0, out

    def job_llm():
        t0 = time.perf_counter()
        llm = llm_from_spec("qwen3:14b", raw=True, think=False)
        raw = llm.chat(
            [{"role": "user", "content": "Reply with the word pong only."}],
            stream=False,
            max_tokens=8,
        )
        content = (raw.get("content") or "") if isinstance(raw, dict) else ""
        return "llm", "pong" in content.lower(), (time.perf_counter() - t0) * 1000.0, content

    wall0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(fn) for fn in (job_procs, job_search, job_llm)]
        parts = [f.result() for f in concurrent.futures.as_completed(futs)]
    wall_ms = (time.perf_counter() - wall0) * 1000.0
    sum_ms = sum(p[2] for p in parts)
    all_ok = all(p[1] for p in parts)
    results.append(
        Result(
            "parallel_tools_wall",
            "parallel",
            ok=all_ok,
            ms=wall_ms,
            detail=f"wall_ms={wall_ms:.0f} sum_ms={sum_ms:.0f} speedup={sum_ms/max(wall_ms,1):.2f}x",
            meta={p[0]: {"ok": p[1], "ms": p[2]} for p in parts},
        )
    )

    # Hive task board
    from amy.host.events import EventBus
    from amy.protocol.messages import HiveTask

    bus = EventBus()
    tid = "bench-task-1"
    bus.upsert_task(
        HiveTask(
            task_id=tid,
            agent_id="scout",
            agent_name="Scout",
            goal="benchmark parallel wait",
            status="running",
            max_steps=4,
        )
    )
    snap = bus.snapshot()
    found = any(t.task_id == tid and t.status == "running" for t in snap.tasks)
    # Simulate wait / poll
    t0 = time.perf_counter()
    seen_running = False
    for _ in range(10):
        if any(t.task_id == tid and t.status == "running" for t in bus.snapshot().tasks):
            seen_running = True
            break
        time.sleep(0.05)
    cancelled = bus.cancel_task(tid)
    wait_ms = (time.perf_counter() - t0) * 1000.0
    results.append(
        Result(
            "hive_task_board_cancel",
            "parallel",
            ok=found and seen_running and bool(cancelled) and bus.is_task_cancelled(tid),
            ms=wait_ms,
            detail=f"found={found} cancelled={bool(cancelled)}",
        )
    )


def _stop_proc(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()


def _ensure_amy_running(results: List[Result]) -> Optional[subprocess.Popen]:
    """Start Amy with a known token if not already listening. Returns proc if we started it."""
    if _port_open("127.0.0.1", AMY_PORT):
        results.append(Result("amy_already_up", "e2e", ok=True, detail=f":{AMY_PORT}"))
        return None

    # Ensure VoiceStudio
    if not _port_open("127.0.0.1", 3900):
        vs_exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "VoiceStudio" / "VoiceStudio.exe"
        if vs_exe.is_file():
            subprocess.Popen([str(vs_exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    env = os.environ.copy()
    env["AMY_TOKEN"] = BENCH_TOKEN
    env["AMY_CHAT_WINDOW"] = "0"
    # Friday OmniVoice turns routinely exceed the default 300s API budget.
    env["AMY_TURN_TIMEOUT_S"] = os.environ.get("AMY_TURN_TIMEOUT_S") or "900"
    cmd = [
        sys.executable,
        "-m",
        "amy",
        "serve",
        "--bind",
        "127.0.0.1",
        "--port",
        str(AMY_PORT),
        "--token",
        BENCH_TOKEN,
        "--no-orb",
        "--no-mic",
        "--force",
    ]
    log_path = ROOT / "logs" / "bench_amy_serve.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logf = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
    )
    atexit.register(_stop_proc, proc)
    results.append(Result("amy_start", "e2e", ok=True, detail=f"pid={proc.pid} log={log_path}"))

    deadline = time.time() + 120.0
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        if "ambient ready" in text or _port_open("127.0.0.1", AMY_PORT):
            # Prefer ambient ready; allow port as soft gate then wait a bit more
            if "ambient ready" in text:
                ready = True
                break
            if _port_open("127.0.0.1", AMY_PORT) and time.time() > deadline - 90:
                # port up early — keep waiting for ambient ready until near timeout
                pass
        time.sleep(0.5)
        if "ambient ready" in text:
            ready = True
            break

    # Final wait for ambient ready up to remaining budget
    if not ready:
        while time.time() < deadline:
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = ""
            if "ambient ready" in text:
                ready = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.4)

    results.append(
        Result(
            "amy_ambient_ready",
            "e2e",
            ok=ready and _port_open("127.0.0.1", AMY_PORT),
            detail=f"ready={ready} port={_port_open('127.0.0.1', AMY_PORT)}",
        )
    )
    return proc


def section_e2e(results: List[Result], *, leave_running: bool = False) -> None:
    proc = _ensure_amy_running(results)
    try:
        _run_e2e(results)
    finally:
        if not leave_running:
            _stop_proc(proc)


def _run_e2e(results: List[Result]) -> None:
    if not _port_open("127.0.0.1", AMY_PORT):
        results.append(Result("e2e_api", "e2e", ok=False, detail="Amy not listening"))
        return

    # Discover token: prefer BENCH_TOKEN; also try env AMY_TOKEN
    token = BENCH_TOKEN
    if os.environ.get("AMY_TOKEN"):
        # If Amy was already up with a different token, health will 401 — try both
        pass

    def _auth_headers(tok: str) -> Dict[str, str]:
        return {"X-Amy-Token": tok, "Authorization": f"Bearer {tok}"}

    def _session(tok: str) -> bool:
        code, body, _ = _json_post(
            f"http://127.0.0.1:{AMY_PORT}/api/session",
            {},
            timeout=15.0,
            headers=_auth_headers(tok),
        )
        return code == 200 and bool((body or {}).get("ok"))

    if not _session(token):
        alt = os.environ.get("AMY_TOKEN") or ""
        if alt and alt != token and _session(alt):
            token = alt
        else:
            # Try scrape token from serve log if we started Amy
            log_path = ROOT / "logs" / "bench_amy_serve.log"
            if log_path.is_file():
                m = re.search(r"token=([A-Za-z0-9_-]+)", log_path.read_text(encoding="utf-8", errors="replace"))
                if m and _session(m.group(1)):
                    token = m.group(1)

    if not _session(token):
        results.append(Result("e2e_session", "e2e", ok=False, detail="auth failed — wrong/missing token"))
        return
    results.append(Result("e2e_session", "e2e", ok=True, detail="token_ok"))

    prompts = [
        ("greeting", "hey, just say hello briefly"),
        ("desktop", "list running processes named notepad if any — one short sentence"),
        ("web", "search what is example.com and summarize in one short sentence"),
    ]
    for key, text in prompts:
        def _turn_once(t: str = text):
            return _json_post(
                f"http://127.0.0.1:{AMY_PORT}/api/turn",
                {"text": t},
                timeout=360.0,
                headers={**_auth_headers(token), "Content-Type": "application/json"},
            )

        try:
            t0 = time.perf_counter()
            code, body, raw = 0, {}, b""
            # Wait out prior turns (Friday TTS can hold the host busy for minutes).
            deadline = time.time() + 420.0
            attempts = 0
            while time.time() < deadline:
                attempts += 1
                code, body, raw = _turn_once()
                err = str((body or {}).get("error") or "")
                if err != "busy" and code != 409:
                    break
                time.sleep(2.0)
            ms = (time.perf_counter() - t0) * 1000.0
            reply = str((body or {}).get("reply") or (body or {}).get("speak") or "")
            err = str((body or {}).get("error") or "")
            ok = (
                code == 200
                and bool((body or {}).get("ok"))
                and "HostNotStarted" not in err
                and err != "busy"
                and bool(reply.strip())
            )
            results.append(
                Result(
                    f"e2e_turn_{key}",
                    "e2e",
                    ok=ok,
                    ms=ms,
                    detail=(reply or err or f"http={code}")[:200],
                    meta={"http": code, "error": err, "attempts": attempts},
                )
            )
        except Exception as e:
            results.append(Result(f"e2e_turn_{key}", "e2e", ok=False, detail=str(e)[:240]))


def _scorecard(results: List[Result]) -> Dict[str, Any]:
    by_sec: Dict[str, List[Result]] = {}
    for r in results:
        by_sec.setdefault(r.section, []).append(r)
    sections = {}
    for sec, items in by_sec.items():
        counted = [i for i in items if not i.skipped]
        passed = sum(1 for i in counted if i.ok)
        sections[sec] = {
            "pass": passed,
            "total": len(counted),
            "skipped": sum(1 for i in items if i.skipped),
            "rate": (passed / len(counted)) if counted else 1.0,
        }
    lat = sorted(r.ms for r in results if r.ms > 0 and not r.skipped)
    def pct(p: float) -> Optional[float]:
        if not lat:
            return None
        idx = min(len(lat) - 1, max(0, int(round((p / 100.0) * (len(lat) - 1)))))
        return lat[idx]

    fails = [r for r in results if not r.ok and not r.skipped]
    gaps = []
    for r in fails[:8]:
        gaps.append(f"{r.section}/{r.name}: {r.detail[:120]}")
    # Always surface known architectural gaps
    if any(r.name == "import_pyautogui" and r.skipped for r in results):
        gaps.append("gap: pyautogui not installed — Amy desktop control is os_* tools, not click automation")
    friday = next((r for r in results if r.name in ("friday_tts_synth", "friday_tts_tool") and r.ms > 8000), None)
    if friday:
        gaps.append(f"gap: Friday TTS slow ({friday.ms:.0f} ms) — cold/warm OmniVoice latency")
    llm = next((r for r in results if "llm" in r.name and r.ms > 5000), None)
    if llm:
        gaps.append(f"gap: remote LLM latency high ({llm.name} {llm.ms:.0f} ms over SSH)")

    overall_counted = [r for r in results if not r.skipped]
    overall_pass = sum(1 for r in overall_counted if r.ok)
    return {
        "ok": overall_pass == len(overall_counted),
        "pass": overall_pass,
        "total": len(overall_counted),
        "sections": sections,
        "latency_ms": {"p50": pct(50), "p95": pct(95), "max": max(lat) if lat else None},
        "top_gaps": gaps[:5],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Amy capability + latency benchmark")
    parser.add_argument("--skip-e2e", action="store_true")
    parser.add_argument("--skip-desktop", action="store_true")
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--keep-amy", action="store_true",
                        help="Leave the Amy server this bench started running after E2E")
    parser.add_argument("--stop-amy", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    # Ensure arsenal on path
    arsenal = os.environ.get("HIVE_ARSENAL") or "H:/New_VLibs/v4"
    if arsenal and arsenal not in sys.path:
        sys.path.insert(0, arsenal)

    from amy.env import apply_env

    apply_env()
    # Defaults for Friday / TTS
    os.environ.setdefault("PYHIVE_TTS_BACKEND", "voicestudio")
    os.environ.setdefault("VOICESTUDIO_BASE_URL", VS_BASE)
    os.environ.setdefault("VOICESTUDIO_VOICE", FRIDAY_VOICE)

    results: List[Result] = []
    t_all = time.perf_counter()

    print("== infra ==")
    section_infra(results)
    if not args.skip_desktop:
        print("== desktop ==")
        section_desktop(results)
    if not args.skip_web:
        print("== web ==")
        section_web(results)
    print("== voice ==")
    section_voice(results)
    print("== parallel ==")
    section_parallel(results)
    if not args.skip_e2e:
        print("== e2e ==")
        section_e2e(results, leave_running=args.keep_amy and not args.stop_amy)

    elapsed = (time.perf_counter() - t_all) * 1000.0
    score = _scorecard(results)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_ms": elapsed,
        "score": score,
        "results": [asdict(r) for r in results],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Console table
    print("\n=== SCORECARD ===")
    for sec, info in score["sections"].items():
        print(f"  {sec:<10} {info['pass']}/{info['total']}  (skip={info['skipped']})")
    lat = score["latency_ms"]

    def _ms(v: Optional[float]) -> str:
        return f"{v:.0f}ms" if v is not None else "-"

    print(f"  latency   p50={_ms(lat['p50'])}  p95={_ms(lat['p95'])}  max={_ms(lat['max'])}")
    print(f"  overall   {score['pass']}/{score['total']}  ({'PASS' if score['ok'] else 'FAIL'})")
    print(f"  report    {REPORT_PATH}")
    if score["top_gaps"]:
        print("  top gaps:")
        for g in score["top_gaps"]:
            print(f"    - {g}")
    for r in results:
        mark = "SKIP" if r.skipped else ("OK  " if r.ok else "FAIL")
        print(f"[{mark}] {r.section}/{r.name}  {r.ms:.0f}ms  {r.detail[:100]}")

    return 0 if score["ok"] else 1


if __name__ == "__main__":
    try:
        # Unbuffered progress when launched from PowerShell / redirected logs.
        try:
            sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        except Exception:
            pass
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130) from None
