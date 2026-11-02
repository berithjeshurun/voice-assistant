"""SmartPanels facade — HTTP first, Playwright fallback."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional

import client_browser
import client_http
from amy.apps.secrets import load_app_secrets, secrets_path, secrets_present, state_dir

APP_ID = "smartpanels"
REQUIRED_KEYS = ("SMARTPANELS_USER", "SMARTPANELS_PASSWORD")
DEFAULT_BASE = client_http.DEFAULT_BASE

_open_lock = threading.Lock()
_open_threads: list[threading.Thread] = []


def _creds() -> Dict[str, str]:
    data = load_app_secrets(APP_ID, env_prefix="SMARTPANELS")
    # Accept USER as email (API expects email)
    user = (data.get("SMARTPANELS_USER") or data.get("SMARTPANELS_EMAIL") or "").strip()
    password = (data.get("SMARTPANELS_PASSWORD") or "").strip()
    base = (data.get("SMARTPANELS_BASE_URL") or DEFAULT_BASE).strip() or DEFAULT_BASE
    return {"user": user, "password": password, "base_url": base}


def status() -> Dict[str, Any]:
    state = state_dir(APP_ID)
    creds = _creds()
    have_secrets = bool(creds["user"] and creds["password"])
    file_exists = secrets_path(APP_ID).is_file()
    sess = client_http.load_session(state)
    sess_ok = client_http.session_looks_valid(sess)
    probe = client_http.probe_dashboard(base_url=creds["base_url"], state=state)
    return {
        "ok": have_secrets,
        "secrets_file": str(secrets_path(APP_ID)),
        "secrets_file_exists": file_exists,
        "secrets_present": have_secrets,
        "session_valid": sess_ok,
        "via": sess.get("via") or "",
        "user_name": (sess.get("user") or {}).get("name") if sess_ok else "",
        "base_url": creds["base_url"],
        "reachable": probe.get("reachable"),
        # never include password / email
    }


def login(*, prefer_browser: bool = False) -> Dict[str, Any]:
    creds = _creds()
    if not creds["user"] or not creds["password"]:
        return {
            "ok": False,
            "error": (
                f"Missing secrets. Add SMARTPANELS_USER and SMARTPANELS_PASSWORD "
                f"to {secrets_path(APP_ID)} (CLI only — never via voice)."
            ),
        }
    state = state_dir(APP_ID)
    if not prefer_browser:
        http_result = client_http.login(
            email=creds["user"],
            password=creds["password"],
            base_url=creds["base_url"],
            state=state,
        )
        if http_result.get("ok"):
            print("# smartpanels_login ok via=http", flush=True)
            return http_result
        http_err = http_result.get("error") or "http failed"
    else:
        http_err = "skipped"

    browser_result = client_browser.login(
        email=creds["user"],
        password=creds["password"],
        base_url=creds["base_url"],
        state=state,
        headless=False,
    )
    if browser_result.get("ok"):
        print("# smartpanels_login ok via=browser", flush=True)
        return browser_result
    return {
        "ok": False,
        "error": f"login failed (http: {http_err}; browser: {browser_result.get('error')})",
        "via": "none",
    }


def logout() -> Dict[str, Any]:
    state = state_dir(APP_ID)
    client_http.clear_session(state)
    client_browser.clear_browser_state(state)
    return {"ok": True, "cleared": True}


def list_rooms() -> Dict[str, Any]:
    creds = _creds()
    return client_http.list_rooms(base_url=creds["base_url"])


def set_room(
    room: str,
    *,
    on: Optional[bool] = None,
    lights: Optional[bool] = None,
    fans: Optional[bool] = None,
    power: Optional[bool] = None,
) -> Dict[str, Any]:
    """Turn room lights/fans/boards on or off. room=name query e.g. 'Meeting Room'."""
    creds = _creds()
    listed = client_http.list_rooms(base_url=creds["base_url"])
    if not listed.get("ok"):
        return listed
    match = client_http.find_room(listed.get("rooms") or [], room)
    if not match:
        names = [str(r.get("name") or "") for r in (listed.get("rooms") or [])]
        return {"ok": False, "error": f"room not found: {room!r}", "rooms": names}

    # Resolve targets: bare on/off → lights+fans+board power
    lights_on = lights
    fans_on = fans
    power_on = power
    if on is not None:
        if lights_on is None:
            lights_on = bool(on)
        if fans_on is None:
            fans_on = bool(on)
        if power_on is None:
            power_on = bool(on)

    room_result: Dict[str, Any] = {"ok": True, "room": match}
    if lights_on is not None or fans_on is not None:
        room_result = client_http.patch_room(
            base_url=creds["base_url"],
            room_id=str(match["id"]),
            lights_on=lights_on,
            fans_on=fans_on,
        )
        if not room_result.get("ok"):
            return room_result

    board_results = []
    offline = [
        str(b.get("name") or b.get("id") or "")
        for b in (match.get("boards") or [])
        if isinstance(b, dict) and not b.get("online")
    ]
    if power_on is not None:
        for b in match.get("boards") or []:
            bid = str(b.get("id") or "")
            if not bid:
                continue
            br = client_http.patch_board(
                base_url=creds["base_url"],
                board_id=bid,
                powered_on=bool(power_on),
            )
            board_results.append(br)

    name = (room_result.get("room") or match).get("name") or room
    print(
        f"# smartpanels_set_room ok room={name!r} "
        f"lights={lights_on} fans={fans_on} power={power_on} "
        f"offline={offline or '-'}",
        flush=True,
    )
    return {
        "ok": True,
        "room": (room_result.get("room") or {"name": name, "id": match.get("id")}),
        "lightsOn": lights_on if lights_on is not None else (room_result.get("room") or {}).get("lightsOn"),
        "fansOn": fans_on if fans_on is not None else (room_result.get("room") or {}).get("fansOn"),
        "power": power_on,
        "offline_boards": [x for x in offline if x],
        "boards": [
            b.get("board") for b in board_results if isinstance(b, dict) and b.get("ok")
        ],
    }


def _keep_browser_open(base_url: str, state: Path) -> Dict[str, Any]:
    """Open headed Edge/Chromium, inject session, keep alive in daemon thread."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "error": "playwright not installed"}

    sess = client_http.load_session(state)
    user = sess.get("user") if isinstance(sess.get("user"), dict) else {}
    base = (base_url or sess.get("base_url") or DEFAULT_BASE).rstrip("/")
    storage_path = state / "storage_state.json"
    result: Dict[str, Any] = {"ok": False}

    def _run() -> None:
        try:
            with sync_playwright() as p:
                browser = client_browser._launch_browser(p, headless=False)
                kwargs: Dict[str, Any] = {}
                if storage_path.is_file():
                    kwargs["storage_state"] = str(storage_path)
                context = browser.new_context(**kwargs)
                page = context.new_page()
                page.goto(base + "/", wait_until="domcontentloaded", timeout=45000)
                if client_http.session_looks_valid({"user": user}):
                    page.evaluate(
                        """([key, user]) => {
                            localStorage.setItem(key, JSON.stringify(user));
                        }""",
                        [client_http.STORAGE_KEY, user],
                    )
                    # Prefer dashboard root after inject
                    page.goto(base + "/", wait_until="domcontentloaded", timeout=45000)
                result.update({"ok": True, "via": "browser", "url": page.url or (base + "/")})
                # Keep headed browser alive until the user closes the window.
                while True:
                    try:
                        if page.is_closed():
                            break
                        page.wait_for_timeout(1000)
                    except Exception:
                        break
                try:
                    browser.close()
                except Exception:
                    pass
        except Exception as e:
            result.update({"ok": False, "error": str(e)[:200]})

    t = threading.Thread(target=_run, name="smartpanels-browser", daemon=True)
    with _open_lock:
        _open_threads.append(t)
    t.start()
    # Brief wait for first result
    t.join(timeout=8.0)
    if result.get("ok"):
        return result
    if t.is_alive():
        # Still starting — assume success; speak without waiting
        return {"ok": True, "via": "browser", "url": base + "/", "pending": True}
    return result if result.get("error") else {"ok": False, "error": "browser open failed"}


def open_dashboard(*, ensure_login: bool = True) -> Dict[str, Any]:
    creds = _creds()
    state = state_dir(APP_ID)
    if ensure_login:
        sess = client_http.load_session(state)
        if not client_http.session_looks_valid(sess):
            logged = login()
            if not logged.get("ok"):
                return logged

    # Prefer Playwright open with session inject; fall back to OS browser URL
    opened = _keep_browser_open(creds["base_url"], state)
    if opened.get("ok"):
        return {
            "ok": True,
            "via": opened.get("via") or "browser",
            "url": opened.get("url") or (creds["base_url"].rstrip("/") + "/"),
            "session_ok": True,
            "user_name": (client_http.load_session(state).get("user") or {}).get("name") or "",
        }

    # Fallback: open URL only (may need manual login if SPA)
    try:
        import webbrowser

        url = creds["base_url"].rstrip("/") + "/"
        webbrowser.open(url)
        return {
            "ok": True,
            "via": "webbrowser",
            "url": url,
            "session_ok": client_http.session_looks_valid(client_http.load_session(state)),
            "note": opened.get("error") or "opened default browser",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
