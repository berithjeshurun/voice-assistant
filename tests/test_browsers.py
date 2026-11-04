from __future__ import annotations

import http.server
import subprocess
import sys
import threading
from pathlib import Path

from amy.host import browsers


def test_env_override_wins(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "mybrowser.exe"
    exe.write_text("")
    monkeypatch.setenv("AMY_CHAT_BROWSER", str(exe))
    monkeypatch.delenv("AMY_ORB_BROWSER", raising=False)
    assert browsers.find_chromium(("AMY_CHAT_BROWSER",)) == [str(exe)]
    assert browsers.find_chromium(("AMY_ORB_BROWSER",)) != [str(exe)]


def test_missing_env_path_is_ignored(monkeypatch) -> None:
    monkeypatch.setenv("AMY_ORB_BROWSER", r"Z:\nope\missing.exe")
    monkeypatch.setattr(browsers, "_windows_candidates", lambda: [])
    monkeypatch.setattr(browsers.shutil, "which", lambda _name: None)
    assert browsers.find_chromium(("AMY_ORB_BROWSER",)) is None


def test_wait_for_http_ok_and_404() -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        assert browsers.wait_for_http(f"http://127.0.0.1:{port}/?view=orb", timeout=5)
    finally:
        srv.shutdown()


def test_wait_for_http_gives_up_and_honours_stop() -> None:
    assert not browsers.wait_for_http("http://127.0.0.1:9/", timeout=0.3, interval=0.05)
    stop = threading.Event()
    stop.set()
    assert not browsers.wait_for_http("http://127.0.0.1:9/", timeout=30, stop=stop)


def test_generated_protocol_is_current() -> None:
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        [sys.executable, str(root / "scripts" / "gen_protocol_ts.py")],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "up to date" in out.stdout, "run: python scripts/gen_protocol_ts.py"
