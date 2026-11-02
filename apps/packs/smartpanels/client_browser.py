"""SmartPanels Playwright fallback — fill /login, persist storage_state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from client_http import STORAGE_KEY, DEFAULT_BASE, load_session, save_session, session_looks_valid

# Selectors for Next.js login form (name=email / name=password)
SEL_EMAIL = 'input[name="email"], input[type="email"]'
SEL_PASSWORD = 'input[name="password"], input[type="password"]'
SEL_SUBMIT = 'button[type="submit"], button:has-text("Login")'


def _storage_state_path(state: Path) -> Path:
    return state / "storage_state.json"


def _launch_browser(playwright, *, headless: bool = False):
    """Prefer Edge channel on Windows; fall back to Chromium."""
    browser_type = playwright.chromium
    for kwargs in (
        {"channel": "msedge", "headless": headless},
        {"channel": "chrome", "headless": headless},
        {"headless": headless},
    ):
        try:
            return browser_type.launch(**kwargs)
        except Exception:
            continue
    return browser_type.launch(headless=headless)


def login(
    *,
    email: str,
    password: str,
    base_url: str,
    state: Path,
    headless: bool = False,
    timeout_ms: int = 45000,
) -> Dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "ok": False,
            "via": "browser",
            "error": "playwright not installed (pip install playwright && playwright install)",
        }

    base = (base_url or DEFAULT_BASE).rstrip("/")
    login_url = f"{base}/login"
    state.mkdir(parents=True, exist_ok=True)
    storage_path = _storage_state_path(state)

    try:
        with sync_playwright() as p:
            browser = _launch_browser(p, headless=headless)
            context = browser.new_context()
            page = context.new_page()
            page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_selector(SEL_EMAIL, timeout=timeout_ms)
            page.fill(SEL_EMAIL, email)
            page.fill(SEL_PASSWORD, password)
            page.click(SEL_SUBMIT)
            # Wait for navigation away from /login or user in localStorage
            try:
                page.wait_for_function(
                    f"""() => {{
                        try {{
                          const raw = localStorage.getItem({json.dumps(STORAGE_KEY)});
                          if (!raw) return false;
                          const u = JSON.parse(raw);
                          return !!(u && u.id && u.username);
                        }} catch (e) {{ return false; }}
                    }}""",
                    timeout=timeout_ms,
                )
            except Exception:
                # Still might have redirected
                if "/login" in (page.url or ""):
                    err = ""
                    try:
                        err = page.locator("text=/invalid|error|failed/i").first.inner_text(timeout=1500)
                    except Exception:
                        pass
                    browser.close()
                    return {
                        "ok": False,
                        "via": "browser",
                        "error": (err or "login did not complete").strip()[:200],
                    }

            user_raw = page.evaluate(f"localStorage.getItem({json.dumps(STORAGE_KEY)})")
            user = {}
            if user_raw:
                try:
                    user = json.loads(user_raw)
                except Exception:
                    user = {}

            context.storage_state(path=str(storage_path))
            browser.close()

            if not session_looks_valid({"user": user}):
                return {"ok": False, "via": "browser", "error": "login completed but no user session"}

            data = {
                "via": "browser",
                "base_url": base,
                "user": user,
                "storage_key": STORAGE_KEY,
                "storage_state": str(storage_path),
            }
            save_session(state, data)
            return {
                "ok": True,
                "via": "browser",
                "user_name": str(user.get("name") or user.get("username") or ""),
            }
    except Exception as e:
        return {"ok": False, "via": "browser", "error": str(e)[:200]}


def open_dashboard(
    *,
    base_url: str,
    state: Path,
    headless: bool = False,
    timeout_ms: int = 45000,
) -> Dict[str, Any]:
    """Open dashboard in headed browser with existing storage_state / inject session."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "ok": False,
            "via": "browser",
            "error": "playwright not installed",
        }

    sess = load_session(state)
    base = (base_url or sess.get("base_url") or DEFAULT_BASE).rstrip("/")
    storage_path = _storage_state_path(state)
    user = sess.get("user") if isinstance(sess.get("user"), dict) else {}

    try:
        with sync_playwright() as p:
            browser = _launch_browser(p, headless=headless)
            ctx_kwargs: Dict[str, Any] = {}
            if storage_path.is_file():
                ctx_kwargs["storage_state"] = str(storage_path)
            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()
            page.goto(base + "/", wait_until="domcontentloaded", timeout=timeout_ms)
            if user and session_looks_valid({"user": user}):
                page.evaluate(
                    """([key, user]) => {
                        localStorage.setItem(key, JSON.stringify(user));
                    }""",
                    [STORAGE_KEY, user],
                )
                page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
            # Leave browser open for the user when headed
            if headless:
                browser.close()
                return {"ok": True, "via": "browser", "url": base + "/", "headless": True}
            # Detach: do not close — user keeps the window
            return {
                "ok": True,
                "via": "browser",
                "url": page.url or (base + "/"),
                "headless": False,
                "note": "browser left open",
            }
    except Exception as e:
        return {"ok": False, "via": "browser", "error": str(e)[:200]}


def clear_browser_state(state: Path) -> None:
    path = _storage_state_path(state)
    if path.is_file():
        path.unlink()
