"""Amy HTTP + WebSocket server — LAN HUD for phones / laptops / Tauri."""

from __future__ import annotations

import asyncio
import secrets
import socket
from pathlib import Path
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from amy.branding import ASSISTANT_NAME, DEFAULT_SERVER_PORT
from amy.host.ambient import AmbientHost
from amy.host.events import EventBus
from amy.protocol.messages import (
    AssistantSnapshot,
    AssistantState,
    ClientCommand,
    HealthInfo,
    TurnRequest,
    TurnResponse,
)


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def create_app(
    host: AmbientHost,
    *,
    token: str,
    lan: bool = False,
    bind: str = "127.0.0.1",
) -> FastAPI:
    bus = host.bus
    app = FastAPI(title=f"{ASSISTANT_NAME} Server", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.amy_host = host
    app.state.amy_token = token
    app.state.amy_lan = lan
    app.state.amy_bind = bind

    def _check_token(
        token_q: Optional[str] = Query(None, alias="token"),
        x_amy_token: Optional[str] = Header(None, alias="X-Amy-Token"),
        authorization: Optional[str] = Header(None),
    ) -> None:
        provided = token_q or x_amy_token
        if not provided and authorization and authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
        if not provided or not secrets.compare_digest(provided, token):
            raise HTTPException(status_code=401, detail="invalid token")

    web_dist = Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"
    web_src_index = Path(__file__).resolve().parents[2] / "apps" / "web" / "index.html"

    @app.on_event("startup")
    async def _startup() -> None:
        bus.set_loop(asyncio.get_running_loop())

    @app.get("/api/health", response_model=HealthInfo)
    def health(_: None = Depends(_check_token)) -> HealthInfo:
        snap = bus.snapshot()
        return HealthInfo(
            ok=True,
            name=ASSISTANT_NAME,
            state=snap.state,
            voice=host.voice_ok,
            wake=host.wake_ok,
            bind=bind,
            lan=lan,
            history=bus.history(),
        )

    @app.get("/api/snapshot", response_model=AssistantSnapshot)
    def snapshot(_: None = Depends(_check_token)) -> AssistantSnapshot:
        return bus.snapshot()

    @app.post("/api/turn", response_model=TurnResponse)
    def turn(body: TurnRequest, _: None = Depends(_check_token)) -> TurnResponse:
        try:
            reply = host.turn_text(body.text)
            return TurnResponse(ok=True, reply=reply, speak=reply, state=bus.snapshot().state)
        except Exception as e:
            return TurnResponse(
                ok=False,
                reply="",
                state=AssistantState.error,
                error=str(e),
            )

    @app.post("/api/wake")
    def wake(_: None = Depends(_check_token)) -> dict:
        host.trigger_wake(reason="api")
        return {"ok": True}

    @app.post("/api/barge")
    def barge(_: None = Depends(_check_token)) -> dict:
        host.barge_in()
        return {"ok": True}

    @app.post("/api/hive/cancel")
    def hive_cancel(body: dict, _: None = Depends(_check_token)) -> dict:
        """Cancel a running Hive specialist task (task board)."""
        tid = str((body or {}).get("task_id") or "").strip()
        if not tid:
            return {"ok": False, "error": "task_id required"}
        task = bus.cancel_task(tid)
        if task is None:
            return {"ok": False, "error": "unknown task_id"}
        return {"ok": True, "task": task.model_dump()}

    @app.post("/api/state")
    def set_state(cmd: ClientCommand, _: None = Depends(_check_token)) -> AssistantSnapshot:
        if cmd.type == "set_state" and cmd.state is not None:
            host.set_ui_state(cmd.state, detail="hud")
        elif cmd.type == "open_hud":
            bus.set_state(bus.snapshot().state, detail="open_hud")
        return bus.snapshot()

    @app.websocket("/ws")
    async def ws_endpoint(
        websocket: WebSocket,
        token_q: Optional[str] = Query(None, alias="token"),
    ) -> None:
        if not token_q or not secrets.compare_digest(token_q, token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        q: asyncio.Queue = asyncio.Queue()
        bus.add_async_queue(q)
        try:
            await websocket.send_json(bus.snapshot().model_dump())
            while True:
                recv_task = asyncio.create_task(websocket.receive_json())
                queue_task = asyncio.create_task(q.get())
                done, pending = await asyncio.wait(
                    {recv_task, queue_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                if queue_task in done:
                    snap = queue_task.result()
                    await websocket.send_json(snap.model_dump())
                if recv_task in done:
                    try:
                        data = recv_task.result()
                    except WebSocketDisconnect:
                        break
                    except Exception:
                        break
                    try:
                        cmd = ClientCommand.model_validate(data)
                    except Exception:
                        continue
                    if cmd.type == "turn" and cmd.text:
                        loop = asyncio.get_running_loop()
                        reply = await loop.run_in_executor(
                            None, host.turn_text, cmd.text
                        )
                        await websocket.send_json(
                            {
                                "type": "turn_result",
                                "reply": reply,
                                "snapshot": bus.snapshot().model_dump(),
                            }
                        )
                    elif cmd.type == "set_state" and cmd.state is not None:
                        host.set_ui_state(cmd.state, detail="ws")
                    elif cmd.type == "wake":
                        host.trigger_wake(reason="ws")
                    elif cmd.type == "barge":
                        host.barge_in()
                    elif cmd.type == "hive_cancel":
                        tid = str(
                            (cmd.payload or {}).get("task_id")
                            or cmd.text
                            or ""
                        ).strip()
                        if tid:
                            bus.cancel_task(tid)
        except WebSocketDisconnect:
            pass
        finally:
            bus.remove_async_queue(q)

    if web_dist.is_dir():
        assets = web_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/")
        def index(token_q: Optional[str] = Query(None, alias="token")) -> FileResponse:
            # Token still required for API; page itself loads and prompts if missing.
            return FileResponse(web_dist / "index.html")

    else:

        @app.get("/", response_class=HTMLResponse)
        def index_fallback() -> str:
            if web_src_index.is_file():
                return web_src_index.read_text(encoding="utf-8")
            return _fallback_html()

    return app


def _fallback_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{ASSISTANT_NAME}</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0b1220;color:#e8eefc;margin:0;padding:1.5rem}}
h1{{font-weight:600}} a{{color:#7eb6ff}}
</style></head><body>
<h1>{ASSISTANT_NAME}</h1>
<p>HUD assets not built yet. API is up — open <code>/api/health?token=…</code></p>
<p>Build the web HUD: <code>cd apps/web && npm install && npm run build</code></p>
</body></html>"""


def run_server(
    host: AmbientHost,
    *,
    bind: str = "127.0.0.1",
    port: int = DEFAULT_SERVER_PORT,
    token: Optional[str] = None,
    lan: bool = False,
) -> int:
    import uvicorn

    tok = token or secrets.token_urlsafe(16)
    if lan and bind in ("127.0.0.1", "localhost"):
        bind = "0.0.0.0"

    app = create_app(host, token=tok, lan=lan, bind=bind)
    lan_host = _lan_ip() if lan else "127.0.0.1"
    link = f"http://{lan_host}:{port}/?token={tok}"
    local = f"http://127.0.0.1:{port}/?token={tok}"
    print(f"# {ASSISTANT_NAME} server token={tok}", flush=True)
    print(f"# local link: {local}", flush=True)
    if lan:
        print(f"# LAN link (phones / laptops): {link}", flush=True)
    uvicorn.run(app, host=bind, port=port, log_level="info")
    return 0
