"""Amy HTTP + WebSocket server — LAN HUD for phones / laptops / Tauri."""

from __future__ import annotations

import asyncio
import os
import secrets
import socket
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from amy.branding import ASSISTANT_NAME, DEFAULT_SERVER_PORT
from amy.host.ambient import AmbientHost
from amy.host.events import EventBus
from amy.protocol.messages import (
    ApprovalAnswer,
    AssistantSnapshot,
    AssistantState,
    ClientCommand,
    HealthInfo,
    LockdownRequest,
    TurnRequest,
    TurnResponse,
)

_AUTH_FAIL_WINDOW_S = 300.0
_AUTH_FAIL_MAX = 20


class _AuthThrottle:
    """Lock out a client IP after repeated bad tokens."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fails: Dict[str, Deque[float]] = defaultdict(deque)

    def _prune(self, ip: str, now: float) -> Deque[float]:
        q = self._fails[ip]
        while q and now - q[0] > _AUTH_FAIL_WINDOW_S:
            q.popleft()
        return q

    def blocked(self, ip: str) -> bool:
        with self._lock:
            return len(self._prune(ip, time.time())) >= _AUTH_FAIL_MAX

    def fail(self, ip: str) -> None:
        with self._lock:
            now = time.time()
            self._prune(ip, now).append(now)


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
    app = FastAPI(title=f"{ASSISTANT_NAME} Server", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    # The HUD is served same-origin; cross-origin callers must be listed explicitly.
    origins = [o.strip() for o in os.environ.get("AMY_CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["X-Amy-Token", "Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    app.state.amy_host = host
    app.state.amy_token = token
    app.state.amy_lan = lan
    app.state.amy_bind = bind
    throttle = _AuthThrottle()

    def _check_token(
        request: Request,
        token_q: Optional[str] = Query(None, alias="token"),
        x_amy_token: Optional[str] = Header(None, alias="X-Amy-Token"),
        authorization: Optional[str] = Header(None),
    ) -> None:
        ip = request.client.host if request.client else "?"
        if throttle.blocked(ip):
            raise HTTPException(status_code=429, detail="too many bad tokens")
        provided = token_q or x_amy_token
        if not provided and authorization and authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
        if not provided or not secrets.compare_digest(provided, token):
            throttle.fail(ip)
            raise HTTPException(status_code=401, detail="invalid token")

    def _guard():
        g = getattr(host, "guard", None)
        if g is None:
            raise HTTPException(status_code=503, detail="guard not ready")
        return g

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

    @app.post("/api/approve")
    def approve(body: ApprovalAnswer, _: None = Depends(_check_token)) -> dict:
        ok = _guard().broker.resolve(body.id, body.approve, via="hud")
        return {"ok": ok, "error": None if ok else "unknown or expired approval"}

    @app.get("/api/guard")
    def guard_status(_: None = Depends(_check_token)) -> dict:
        g = _guard()
        return {**g.status(), "pending": len(g.broker.pending())}

    @app.post("/api/guard/lockdown")
    def guard_lockdown(body: LockdownRequest, _: None = Depends(_check_token)) -> dict:
        g = _guard()
        g.set_lockdown(body.on, via="hud")
        return {"ok": True, **g.status()}

    @app.post("/api/state")
    def set_state(cmd: ClientCommand, _: None = Depends(_check_token)) -> AssistantSnapshot:
        if cmd.type == "set_state" and cmd.state is not None:
            host.set_ui_state(cmd.state, detail="hud")
        elif cmd.type == "open_hud":
            try:
                from amy.host.hud_window import open_hud_subprocess

                open_hud_subprocess(
                    host="127.0.0.1",
                    port=int(os.environ.get("AMY_PORT") or DEFAULT_SERVER_PORT),
                    token=token,
                )
            except Exception as e:
                bus.set_state(bus.snapshot().state, detail=f"open_hud:{e}")
            else:
                bus.set_state(bus.snapshot().state, detail="open_hud")
        return bus.snapshot()

    @app.post("/api/open_hud")
    def open_hud(_: None = Depends(_check_token)) -> dict:
        """Open the Amy HUD as a desktop webview app (not a browser tab)."""
        from amy.host.hud_window import open_hud_subprocess

        ok = open_hud_subprocess(
            host="127.0.0.1",
            port=int(os.environ.get("AMY_PORT") or DEFAULT_SERVER_PORT),
            token=token,
        )
        return {"ok": bool(ok)}

    @app.get("/api/system")
    def system_metrics(_: None = Depends(_check_token)) -> dict:
        from amy.system.metrics import sample_system

        return sample_system()

    @app.get("/api/tools/catalog")
    def tools_catalog_api(
        category: str = "",
        _: None = Depends(_check_token),
    ) -> dict:
        from amy.tools.catalog import get_tool_catalog

        return get_tool_catalog().catalog(category)

    @app.get("/api/updates")
    def updates_api(
        check: bool = False,
        _: None = Depends(_check_token),
    ) -> dict:
        from amy.updates.checker import get_update_checker

        chk = get_update_checker()
        if check:
            return chk.check(force=False)
        return chk.status()

    @app.get("/api/vision/status")
    def vision_status_api(_: None = Depends(_check_token)) -> dict:
        from amy.vision.service import get_vision_service

        return get_vision_service().status()

    @app.post("/api/vision/enroll")
    def vision_enroll_api(body: dict, _: None = Depends(_check_token)) -> dict:
        from amy.vision.service import get_vision_service

        return get_vision_service().enroll(
            str((body or {}).get("name") or ""),
            image_path=str((body or {}).get("image_path") or ""),
            from_camera=bool((body or {}).get("from_camera")),
        )

    @app.get("/api/alerts")
    def alerts_api(
        limit: int = 20,
        _: None = Depends(_check_token),
    ) -> dict:
        from amy.workers.alerts import get_alert_bus

        return {"ok": True, "alerts": get_alert_bus().list(limit=limit)}

    @app.get("/api/settings")
    def settings_get(_: None = Depends(_check_token)) -> dict:
        from amy.settings.store import get_settings_store

        return {"ok": True, **get_settings_store().options()}

    @app.post("/api/settings")
    def settings_set(body: dict, _: None = Depends(_check_token)) -> dict:
        from amy.settings.store import get_settings_store

        snap = get_settings_store().update(body or {})
        # Push persona block into live agent when host is up.
        try:
            shell = getattr(host, "shell", None)
            agent = getattr(shell, "_agent", None) if shell else None
            if agent is not None:
                from amy.settings.store import get_settings_store as _gs

                block = _gs().persona_prompt_block()
                sp = getattr(agent, "system_prompt", "") or ""
                marker = "\n\nPERSONA PRESET ("
                if marker in sp:
                    sp = sp.split(marker)[0]
                agent.system_prompt = sp + block
        except Exception:
            pass
        return {"ok": True, "settings": snap}

    @app.get("/api/integrations")
    def integrations_list(_: None = Depends(_check_token)) -> dict:
        from amy.settings.integrations import list_integrations

        return list_integrations()

    @app.post("/api/integrations/{integration_id}")
    def integrations_set(
        integration_id: str,
        body: dict,
        _: None = Depends(_check_token),
    ) -> dict:
        from amy.settings.integrations import set_integration_secrets

        values = (body or {}).get("secrets") or body or {}
        if not isinstance(values, dict):
            return {"ok": False, "error": "secrets object required"}
        return set_integration_secrets(integration_id, values)

    @app.get("/api/packs")
    def packs_list(_: None = Depends(_check_token)) -> dict:
        from amy.apps.loader import discover_packs, enabled_pack_ids, packs_roots

        packs = [
            {
                "id": p["id"],
                "name": p["name"],
                "steam_root": p.get("steam_root"),
                "path": str(p.get("path")),
            }
            for p in discover_packs()
        ]
        return {
            "ok": True,
            "roots": [str(r) for r in packs_roots()],
            "enabled": enabled_pack_ids(),
            "packs": packs,
        }

    @app.get("/api/config")
    def config_studio_get(_: None = Depends(_check_token)) -> dict:
        from amy.config_studio import get_config_studio

        return get_config_studio()

    @app.post("/api/config")
    def config_studio_set(body: dict, _: None = Depends(_check_token)) -> dict:
        from amy.config_studio import update_config_studio

        return update_config_studio(body or {})

    @app.websocket("/ws")
    async def ws_endpoint(
        websocket: WebSocket,
        token_q: Optional[str] = Query(None, alias="token"),
    ) -> None:
        ip = websocket.client.host if websocket.client else "?"
        if throttle.blocked(ip):
            await websocket.close(code=4429)
            return
        if not token_q or not secrets.compare_digest(token_q, token):
            throttle.fail(ip)
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
                    elif cmd.type == "approve":
                        g = getattr(host, "guard", None)
                        aid = str((cmd.payload or {}).get("id") or "").strip()
                        if g is not None and aid:
                            g.broker.resolve(
                                aid, bool((cmd.payload or {}).get("approve")), via="hud"
                            )
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
