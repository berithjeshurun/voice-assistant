"""Persistent always-on-top Amy orb — React Bits Crystalized Ball.

Loads the web HUD at ``/?view=orb`` (CrystalizedBall). Prefers frameless
pywebview (headerless rounded panel); Chromium ``--app`` only when
``AMY_ORB_MODE=chromium``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from amy.branding import ASSISTANT_NAME, DEFAULT_SERVER_PORT


def _orb_url(host: str, port: int, token: str, hud_url: str = "") -> str:
    if hud_url:
        base = hud_url
    else:
        base = f"http://{host}:{port}/"
    parsed = urllib.parse.urlparse(base)
    q = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    q["view"] = "orb"
    if token:
        q["token"] = token
    return urllib.parse.urlunparse(
        (
            parsed.scheme or "http",
            parsed.netloc or f"{host}:{port}",
            parsed.path or "/",
            "",
            urllib.parse.urlencode(q),
            "",
        )
    )


def _spawn_hud_from_orb_url(url: str) -> None:
    try:
        from amy.host.hud_window import open_hud_subprocess

        parsed = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(parsed.query))
        open_hud_subprocess(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or DEFAULT_SERVER_PORT,
            token=q.get("token") or os.environ.get("AMY_TOKEN", ""),
        )
    except Exception as e:
        print(f"# amy orb open_hud failed: {e}", flush=True)


def _wait_for_hud(url: str, timeout: float = 45.0) -> bool:
    """Poll until the HUD answers (server must be up before WebGL orb loads)."""
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
        time.sleep(0.4)
    return False


def _find_chromium() -> Optional[list[str]]:
    env = os.environ.get("AMY_ORB_BROWSER", "").strip()
    if env and Path(env).is_file():
        return [env]
    candidates: list[str] = []
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates.extend(
            [
                str(Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                str(Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                str(Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe"),
                str(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            ]
        )
        which = shutil.which("msedge") or shutil.which("chrome")
        if which:
            candidates.insert(0, which)
    else:
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            which = shutil.which(name)
            if which:
                candidates.append(which)
    for c in candidates:
        if c and Path(c).is_file():
            return [c]
    return None


def _run_pywebview(url: str) -> bool:
    try:
        import webview  # type: ignore
    except Exception as e:
        print(f"# amy orb webview import failed: {e}", flush=True)
        return False
    from amy.host.placement import orb_rect

    r = orb_rect()
    # Opaque dark + frameless — DWM rounds corners (no transparent white bleed).
    kwargs = dict(
        title=ASSISTANT_NAME,
        url=url,
        width=r.w,
        height=r.h,
        x=r.x,
        y=r.y,
        on_top=True,
        frameless=True,
        easy_drag=True,
        resizable=False,
        transparent=False,
        background_color="#071018",
        shadow=False,
    )
    try:
        try:
            window = webview.create_window(**kwargs)
        except TypeError:
            kwargs.pop("shadow", None)
            window = webview.create_window(**kwargs)
        except ValueError:
            kwargs["background_color"] = "#000000"
            window = webview.create_window(**kwargs)
    except Exception as e:
        print(f"# amy orb webview create failed: {e}", flush=True)
        return False

    print(
        json.dumps({"type": "renderer_ready", "name": ASSISTANT_NAME, "mode": "webview"}),
        flush=True,
    )

    def _on_shown() -> None:
        try:
            from amy.host.win_chrome import style_amy_window

            style_amy_window(ASSISTANT_NAME)
        except Exception:
            pass
        try:
            window.events.double_click += lambda: _spawn_hud_from_orb_url(url)
        except Exception:
            pass

    try:
        try:
            webview.start(_on_shown, gui="edgechromium")
        except Exception:
            webview.start(_on_shown)
    except Exception as e:
        print(f"# amy orb webview start failed: {e}", flush=True)
        return False
    return True


def _run_app_browser(url: str) -> bool:
    from amy.host.chromium_app import (
        profile_alive,
        spawn_app,
        wait_for_profile_exit,
    )
    from amy.host.placement import orb_rect

    r = orb_rect()
    # One orb only — kill prior Edge orb windows for this profile first.
    proc = spawn_app(
        url=url,
        profile_name="orb",
        rect=r,
        title_class="AmyOrb",
        replace_existing=True,
        always_on_top=True,
    )
    if proc is None and not profile_alive("orb"):
        return False
    print(
        json.dumps({"type": "renderer_ready", "name": ASSISTANT_NAME, "mode": "chromium-app"}),
        flush=True,
    )
    # Keep sidecar alive while the app window runs; stdin kept for protocol compat.
    stop = threading.Event()

    def _stdin() -> None:
        while not stop.is_set():
            line = sys.stdin.readline()
            if not line:
                time.sleep(0.05)
                continue
            # State is driven by WebSocket in the page; ignore set_state noise.
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("type") == "open_hud":
                _spawn_hud_from_orb_url(url)

    threading.Thread(target=_stdin, name="amy-orb-stdin", daemon=True).start()
    try:
        # Edge often exits the launcher PID immediately while the real window
        # keeps running under the same user-data-dir — wait on the profile.
        time.sleep(0.8)
        wait_for_profile_exit("orb", poll_s=1.0)
    finally:
        stop.set()
    return True


def _run_tk_fallback(url: str, token: str) -> None:
    """Minimal always-on-top chip if no browser/WebView is available."""
    import math
    import tkinter as tk

    from amy.protocol.messages import AssistantState

    colors = {
        AssistantState.idle: "#3f738c",
        AssistantState.listening: "#4db8e8",
        AssistantState.thinking: "#e8a24a",
        AssistantState.speaking: "#3dcea7",
        AssistantState.needs_approval: "#f08a3a",
        AssistantState.error: "#e06b6b",
    }
    from amy.host.placement import orb_rect

    r = orb_rect()
    size = min(r.w, r.h, 160)
    state = AssistantState.idle
    root = tk.Tk()
    root.title(ASSISTANT_NAME)
    root.geometry(f"{size}x{size}+{r.x}+{r.y}")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.overrideredirect(True)
    canvas = tk.Canvas(root, width=size, height=size, highlightthickness=0, bg="#071018")
    canvas.pack(fill="both", expand=True)
    core = canvas.create_oval(20, 20, size - 20, size - 20, fill="#3f738c", outline="")
    label = canvas.create_text(
        size // 2, size // 2, text="Orb\nneeds\nbrowser", fill="#e7f0f7", font=("Segoe UI", 9)
    )
    drag = {"x": 0, "y": 0}
    t0 = time.time()

    def open_hud(_e=None) -> None:
        _spawn_hud_from_orb_url(url)

    def on_click(e: tk.Event) -> None:
        drag["x"], drag["y"] = e.x, e.y
        open_hud()

    def on_drag(e: tk.Event) -> None:
        root.geometry(f"+{root.winfo_x() + e.x - drag['x']}+{root.winfo_y() + e.y - drag['y']}")

    canvas.bind("<Button-1>", on_click)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<Button-3>", lambda _e: root.destroy())

    stop = threading.Event()

    def tick() -> None:
        if stop.is_set():
            return
        pulse = 0.08 * math.sin((time.time() - t0) * 1.2)
        pad = int(size * (0.18 - pulse))
        canvas.itemconfigure(core, fill=colors.get(state, "#3f738c"))
        canvas.coords(core, pad, pad, size - pad, size - pad)
        root.after(33, tick)

    def stdin_loop() -> None:
        nonlocal state
        while not stop.is_set():
            line = sys.stdin.readline()
            if not line:
                time.sleep(0.05)
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("type") == "set_state" and msg.get("state"):
                try:
                    state = AssistantState(str(msg["state"]))
                except ValueError:
                    state = AssistantState.idle

    print(
        json.dumps({"type": "renderer_ready", "name": ASSISTANT_NAME, "mode": "tk-fallback"}),
        flush=True,
    )
    threading.Thread(target=stdin_loop, daemon=True).start()
    tick()
    try:
        root.mainloop()
    finally:
        stop.set()


def run_orb(
    *,
    host: str = "127.0.0.1",
    port: int = DEFAULT_SERVER_PORT,
    token: str = "",
    hud_url: str = "",
) -> int:
    token = token or os.environ.get("AMY_TOKEN", "")
    url = _orb_url(host, port, token, hud_url)
    print(f"# amy orb crystalized url={url}", flush=True)
    if not _wait_for_hud(url, timeout=20.0):
        print("# amy orb: HUD not ready yet — opening anyway", flush=True)

    mode = (os.environ.get("AMY_ORB_MODE") or "webview").strip().lower()
    # Default: frameless pywebview (headerless, rounded CSS panel). Chromium
    # --app keeps a title bar unless heavily hacked — only use when forced.
    if mode in ("auto", "webview") and _run_pywebview(url):
        return 0
    if mode in ("browser", "chromium") and _run_app_browser(url):
        return 0
    # Opt-in only: AMY_ORB_MODE=tk (not a production ship path).
    if mode == "tk":
        _run_tk_fallback(url, token)
        return 0
    if mode == "auto" and _run_app_browser(url):
        return 0
    print(
        "# amy orb: pip install pywebview (preferred) or set AMY_ORB_MODE=chromium",
        flush=True,
    )
    return 1


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=f"{ASSISTANT_NAME} companion orb (Crystalized Ball)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT)
    p.add_argument("--token", default=os.environ.get("AMY_TOKEN", ""))
    p.add_argument("--hud-url", default="")
    args = p.parse_args(argv)
    return run_orb(host=args.host, port=args.port, token=args.token, hud_url=args.hud_url)


if __name__ == "__main__":
    raise SystemExit(main())
