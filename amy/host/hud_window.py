"""Amy HUD as a desktop webview application (not a browser tab)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from amy.branding import ASSISTANT_NAME, DEFAULT_SERVER_PORT

_lock = threading.Lock()
_proc_thread: Optional[threading.Thread] = None
_alive = threading.Event()


def _hud_url(host: str, port: int, token: str, path: str = "/") -> str:
    q = {}
    if token:
        q["token"] = token
    query = urllib.parse.urlencode(q)
    return f"http://{host}:{int(port)}{path}{'?' + query if query else ''}"


def _wait(url: str, timeout: float = 20.0) -> bool:
    import time

    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(origin + "/", timeout=2) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def run_hud(
    *,
    host: str = "127.0.0.1",
    port: int = DEFAULT_SERVER_PORT,
    token: str = "",
    url: str = "",
) -> int:
    """Block in a frameless pywebview HUD window."""
    try:
        import webview  # type: ignore
    except Exception as e:
        print(f"# amy hud: pywebview required ({e})", flush=True)
        return 1

    from amy.host.placement import hud_rect

    token = token or os.environ.get("AMY_TOKEN", "")
    target = url or _hud_url(host, port, token)
    _wait(target, timeout=12.0)
    r = hud_rect()
    kwargs = dict(
        title=f"{ASSISTANT_NAME} HUD",
        url=target,
        width=r.w,
        height=r.h,
        x=r.x,
        y=r.y,
        on_top=False,
        frameless=False,  # HUD may keep a thin frame for resize; still app window
        easy_drag=False,
        resizable=True,
        transparent=False,
        background_color="#071018",
        shadow=True,
    )
    # Prefer frameless app chrome for product feel — still not a browser tab.
    kwargs["frameless"] = True
    kwargs["easy_drag"] = True
    try:
        try:
            window = webview.create_window(**kwargs)
        except TypeError:
            kwargs.pop("shadow", None)
            window = webview.create_window(**kwargs)
    except Exception as e:
        print(f"# amy hud create failed: {e}", flush=True)
        return 1

    print(json.dumps({"type": "hud_ready", "name": ASSISTANT_NAME}), flush=True)

    def _shown() -> None:
        try:
            from amy.host.win_chrome import style_amy_window

            style_amy_window(f"{ASSISTANT_NAME} HUD")
        except Exception:
            pass
        _ = window

    try:
        try:
            webview.start(_shown, gui="edgechromium")
        except Exception:
            webview.start(_shown)
    except Exception as e:
        print(f"# amy hud start failed: {e}", flush=True)
        return 1
    return 0


def open_hud_async(
    *,
    host: str = "127.0.0.1",
    port: int = DEFAULT_SERVER_PORT,
    token: str = "",
    url: str = "",
) -> bool:
    """Spawn HUD in a daemon thread if not already open (same process)."""
    global _proc_thread
    with _lock:
        if _proc_thread and _proc_thread.is_alive():
            return True

        def _run() -> None:
            _alive.set()
            try:
                run_hud(host=host, port=port, token=token, url=url)
            finally:
                _alive.clear()

        _proc_thread = threading.Thread(target=_run, name="amy-hud-webview", daemon=True)
        _proc_thread.start()
        return True


def open_hud_subprocess(
    *,
    host: str = "127.0.0.1",
    port: int = DEFAULT_SERVER_PORT,
    token: str = "",
) -> bool:
    """Launch HUD as a separate Python process (preferred from server host)."""
    import subprocess

    env = os.environ.copy()
    if token:
        env["AMY_TOKEN"] = token
    try:
        log_dir = Path(os.environ.get("AMY_LOG_DIR") or Path.home() / ".amy" / "logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "hud_window.log"
        log_fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 — kept for subprocess life
        log_fh.write(f"\n# spawn {host}:{port}\n")
        log_fh.flush()
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "amy.host.hud_window",
                "--host",
                host,
                "--port",
                str(port),
                "--token",
                token or "",
            ],
            env=env,
            stdout=log_fh,
            stderr=log_fh,
        )
        return True
    except Exception as e:
        print(f"# amy hud spawn failed: {e}", flush=True)
        return False


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=f"{ASSISTANT_NAME} HUD webview app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT)
    p.add_argument("--token", default=os.environ.get("AMY_TOKEN", ""))
    p.add_argument("--url", default="")
    args = p.parse_args(argv)
    return run_hud(host=args.host, port=args.port, token=args.token, url=args.url)


if __name__ == "__main__":
    raise SystemExit(main())
