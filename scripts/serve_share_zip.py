"""Blazing-fast LAN share for Amy platform zip (FastAPI + Range support)."""

from __future__ import annotations

import argparse
import os
import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

DEFAULT_ZIP = Path(
    os.path.expandvars(r"%USERPROFILE%\OneDrive\Desktop\Amy-Platform-Share-20261104-1139.zip")
)
FALLBACK_ZIP = Path(os.path.expandvars(r"%USERPROFILE%\Desktop\Amy-Platform-Share-20261104-1139.zip"))


def resolve_zip(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.is_file():
            raise SystemExit(f"zip not found: {p}")
        return p
    for cand in (DEFAULT_ZIP, FALLBACK_ZIP):
        if cand.is_file():
            return cand.resolve()
    desk = Path(os.path.expandvars(r"%USERPROFILE%\OneDrive\Desktop"))
    matches = sorted(desk.glob("Amy-Platform-Share-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not matches:
        desk2 = Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))
        matches = sorted(desk2.glob("Amy-Platform-Share-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not matches:
        raise SystemExit("No Amy-Platform-Share-*.zip found on Desktop")
    return matches[0].resolve()


def lan_ips() -> list[str]:
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    # UDP trick for primary outbound interface
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips and not ip.startswith("127."):
            ips.insert(0, ip)
    except Exception:
        pass
    return ips or ["127.0.0.1"]


def build_app(zip_path: Path) -> FastAPI:
    app = FastAPI(title="Amy Platform Share", docs_url=None, redoc_url=None)
    name = zip_path.name
    size = zip_path.stat().st_size

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        gb = size / (1024**3)
        links = "".join(
            f'<li><a href="http://{ip}:{os.environ.get("AMY_SHARE_PORT", "8799")}/download">{ip}</a></li>'
            for ip in lan_ips()
        )
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Amy Platform Share</title>
<style>
body{{font-family:system-ui,sans-serif;background:#071018;color:#e7f0f7;margin:2rem}}
a{{color:#4db8e8}} .card{{border:1px solid rgba(77,184,232,.25);border-radius:12px;padding:1.25rem;max-width:40rem}}
</style></head><body>
<div class="card">
<h1>Amy Platform Share</h1>
<p><strong>{name}</strong> · {gb:.2f} GB</p>
<p><a href="/download">⬇ Download zip</a> (Range / resume supported)</p>
<p>LAN mirrors:</p><ul>{links}</ul>
</div></body></html>"""

    @app.get("/download")
    def download():
        if not zip_path.is_file():
            raise HTTPException(404, "zip missing")
        return FileResponse(
            path=str(zip_path),
            filename=name,
            media_type="application/zip",
            stat_result=zip_path.stat(),
            # Starlette FileResponse supports HTTP Range for resumable downloads
        )

    @app.get("/health")
    def health():
        return {"ok": True, "file": name, "bytes": size}

    @app.get("/file")
    def file_alias():
        return RedirectResponse("/download")

    return app


def main() -> None:
    p = argparse.ArgumentParser(description="Serve Amy share zip on the LAN")
    p.add_argument("--zip", default="", help="Path to zip (default: newest Desktop share)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8799)
    args = p.parse_args()
    zip_path = resolve_zip(args.zip or None)
    os.environ["AMY_SHARE_PORT"] = str(args.port)
    app = build_app(zip_path)

    print(f"# serving {zip_path}", flush=True)
    print(f"# size    {zip_path.stat().st_size / (1024**3):.2f} GB", flush=True)
    for ip in lan_ips():
        print(f"# link    http://{ip}:{args.port}/download", flush=True)
    print(f"# local   http://127.0.0.1:{args.port}/download", flush=True)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        # keep-alive + no reload for max throughput
        timeout_keep_alive=75,
        limit_concurrency=64,
    )


if __name__ == "__main__":
    main()
