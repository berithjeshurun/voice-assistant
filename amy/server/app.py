"""Amy HTTP + WebSocket server — LAN HUD for phones / laptops / Tauri."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import logging
import os
import re
import secrets
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, Optional
from urllib.parse import urlsplit

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from amy.branding import ASSISTANT_NAME, DEFAULT_SERVER_PORT
from amy.errors import HostBusy
from amy.host.events import snapshot_patch
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
from amy.server.auth import (
    SESSION_COOKIE,
    Authenticator,
    AuthThrottle,
    DeviceRegistry,
    Principal,
)

_logger = logging.getLogger(__name__)

# Live-update pacing per WebSocket client: at most ~20 messages/s, bursts coalesce.
_WS_MIN_INTERVAL_S = 0.05
_MAX_WS_CLIENTS = int(os.environ.get("AMY_MAX_CLIENTS") or 32)
_TURN_TIMEOUT_S = float(os.environ.get("AMY_TURN_TIMEOUT_S") or 300)


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return str(ip)
    except OSError:
        return "127.0.0.1"


def _inline_script_hashes(index_html: Path) -> list[str]:
    try:
        html = index_html.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for body in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I):
        digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        out.append(f"'sha256-{digest}'")
    return out


def _csp(script_hashes: list[str]) -> str:
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' " + " ".join(script_hashes),
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' data: https://fonts.gstatic.com",
            "img-src 'self' data: blob: https:",
            "connect-src 'self' ws: wss:",
            "worker-src 'self' blob:",
            "object-src 'none'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        ]
    )


def _is_busy(e: BaseException) -> bool:
    return isinstance(e, HostBusy)


def create_app(
    host: Any,
    *,
    token: str,
    lan: bool = False,
    bind: str = "127.0.0.1",
    devices: Optional[DeviceRegistry] = None,
    turn_workers: int = 2,
    secure_cookies: bool = False,
) -> FastAPI:
    bus = host.bus
    auth = Authenticator(token, devices=devices, throttle=AuthThrottle())
    turn_pool = ThreadPoolExecutor(max_workers=max(1, turn_workers), thread_name_prefix="amy-turn")

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        bus.set_loop(asyncio.get_running_loop())
        try:
            yield
        finally:
            turn_pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(
        title=f"{ASSISTANT_NAME} Server",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    # The HUD is served same-origin; cross-origin callers must be listed explicitly.
    origins = [o.strip() for o in os.environ.get("AMY_CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["X-Amy-Token", "Authorization", "Content-Type"],
        )

    web_dist = Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"
    web_src_index = Path(__file__).resolve().parents[2] / "apps" / "web" / "index.html"
    csp = _csp(_inline_script_hashes(web_dist / "index.html"))

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: Callable[..., Any]) -> Response:
        resp: Response = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Content-Security-Policy"] = csp
        resp.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
        return resp

    app.state.amy_host = host
    app.state.amy_token = token
    app.state.amy_lan = lan
    app.state.amy_bind = bind
    app.state.amy_auth = auth

    def _authenticate(
        request: Request,
        token_q: Optional[str],
        x_amy_token: Optional[str],
        authorization: Optional[str],
    ) -> Principal:
        ip = request.client.host if request.client else "?"
        if auth.throttle.blocked(ip):
            raise HTTPException(status_code=429, detail="too many bad tokens")
        provided = token_q or x_amy_token
        if not provided and authorization and authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
        if provided:
            p = auth.from_token(provided)
        else:
            p = auth.from_session(request.cookies.get(SESSION_COOKIE))
        if p is None:
            auth.throttle.fail(ip)
            raise HTTPException(status_code=401, detail="invalid token")
        return p

    def need(role: str) -> Callable[..., Principal]:
        def dep(
            request: Request,
            token_q: Optional[str] = Query(None, alias="token"),
            x_amy_token: Optional[str] = Header(None, alias="X-Amy-Token"),
            authorization: Optional[str] = Header(None),
        ) -> Principal:
            p = _authenticate(request, token_q, x_amy_token, authorization)
            if not p.can(role):
                raise HTTPException(status_code=403, detail=f"requires {role} role")
            return p

        return dep

    viewer, user, admin = need("viewer"), need("user"), need("admin")

    def _guard() -> Any:
        g = getattr(host, "guard", None)
        if g is None:
            raise HTTPException(status_code=503, detail="guard not ready")
        return g

    async def _run_turn(text: str) -> str:
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(turn_pool, host.turn_text, text)
        return str(await asyncio.wait_for(fut, timeout=_TURN_TIMEOUT_S))

    # --- session -----------------------------------------------------------------

    @app.post("/api/session")
    def session_open(request: Request, response: Response, p: Principal = Depends(viewer)) -> dict:
        """Trade a token (header/query) for an HttpOnly session cookie."""
        https = secure_cookies or request.url.scheme == "https"
        response.set_cookie(
            SESSION_COOKIE,
            auth.signer.issue(p),
            max_age=int(auth.signer.ttl_s),
            httponly=True,
            samesite="strict",
            secure=https,
            path="/",
        )
        return {"ok": True, "name": p.name, "role": p.role}

    @app.delete("/api/session")
    def session_close(response: Response) -> dict:
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/whoami")
    def whoami(p: Principal = Depends(viewer)) -> dict:
        return {"ok": True, "name": p.name, "role": p.role}

    # --- state ---------------------------------------------------------------------

    @app.get("/api/health", response_model=HealthInfo)
    def health(_: Principal = Depends(viewer)) -> HealthInfo:
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

    @app.get("/api/history")
    def history(
        limit: int = Query(100, ge=1, le=1000),
        q: str = Query("", max_length=200),
        _: Principal = Depends(viewer),
    ) -> dict:
        store = getattr(bus, "history_store", None)
        if q.strip():
            if store is None:
                needle = q.strip().lower()
                items = [m for m in bus.history() if needle in m.text.lower()][-limit:]
            else:
                items = store.search(q.strip(), limit=limit)
        elif store is not None and limit > len(bus.history()):
            items = store.recent(limit)
        else:
            items = bus.history()[-limit:]
        return {"ok": True, "history": [m.model_dump() for m in items]}

    @app.get("/api/snapshot", response_model=AssistantSnapshot)
    def snapshot(_: Principal = Depends(viewer)) -> AssistantSnapshot:
        return bus.snapshot()

    @app.get("/api/doctor")
    def doctor(_: Principal = Depends(admin)) -> dict:
        from amy.doctor import runtime_checks, static_checks, summarize

        return summarize(runtime_checks(host) + static_checks(probe_network=True, timeout=1.5))

    @app.post("/api/turn", response_model=TurnResponse)
    async def turn(body: TurnRequest, response: Response, _: Principal = Depends(user)) -> TurnResponse:
        try:
            reply = await _run_turn(body.text)
            return TurnResponse(ok=True, reply=reply, speak=reply, state=bus.snapshot().state)
        except Exception as e:
            if _is_busy(e):
                response.status_code = 409
                return TurnResponse(ok=False, state=bus.snapshot().state, error="busy")
            if isinstance(e, asyncio.TimeoutError):
                response.status_code = 504
                return TurnResponse(ok=False, state=AssistantState.error, error="turn timed out")
            _logger.exception("turn failed")
            return TurnResponse(ok=False, reply="", state=AssistantState.error, error=str(e))

    @app.post("/api/wake")
    def wake(_: Principal = Depends(user)) -> dict:
        host.trigger_wake(reason="api")
        return {"ok": True}

    @app.post("/api/barge")
    def barge(_: Principal = Depends(user)) -> dict:
        host.barge_in()
        return {"ok": True}

    @app.post("/api/hive/cancel")
    def hive_cancel(body: dict, _: Principal = Depends(user)) -> dict:
        """Cancel a running Hive specialist task (task board)."""
        tid = str((body or {}).get("task_id") or "").strip()
        if not tid:
            return {"ok": False, "error": "task_id required"}
        task = bus.cancel_task(tid)
        if task is None:
            return {"ok": False, "error": "unknown task_id"}
        return {"ok": True, "task": task.model_dump()}

    # --- guard -----------------------------------------------------------------------

    @app.post("/api/approve")
    def approve(body: ApprovalAnswer, p: Principal = Depends(admin)) -> dict:
        ok = _guard().broker.resolve(body.id, body.approve, via=f"hud:{p.name}")
        return {"ok": ok, "error": None if ok else "unknown or expired approval"}

    @app.get("/api/guard")
    def guard_status(_: Principal = Depends(viewer)) -> dict:
        g = _guard()
        return {**g.status(), "pending": len(g.broker.pending())}

    @app.post("/api/guard/lockdown")
    def guard_lockdown(body: LockdownRequest, p: Principal = Depends(user)) -> dict:
        # anyone who may talk to Amy may lock her down; only an admin may lift it
        if not body.on and not p.can("admin"):
            raise HTTPException(status_code=403, detail="requires admin role")
        g = _guard()
        g.set_lockdown(body.on, via=f"hud:{p.name}")
        return {"ok": True, **g.status()}

    # --- ui ----------------------------------------------------------------------------

    def _open_hud() -> bool:
        from amy.host.hud_window import open_hud_subprocess

        return bool(
            open_hud_subprocess(
                host="127.0.0.1",
                port=int(os.environ.get("AMY_PORT") or DEFAULT_SERVER_PORT),
                token=token,
            )
        )

    @app.post("/api/state")
    def set_state(cmd: ClientCommand, _: Principal = Depends(user)) -> AssistantSnapshot:
        if cmd.type == "set_state" and cmd.state is not None:
            host.set_ui_state(cmd.state, detail="hud")
        elif cmd.type == "open_hud":
            try:
                _open_hud()
            except Exception as e:
                _logger.warning("open_hud failed: %s", e)
                bus.set_state(bus.snapshot().state, detail=f"open_hud:{e}")
            else:
                bus.set_state(bus.snapshot().state, detail="open_hud")
        return bus.snapshot()

    @app.post("/api/open_hud")
    def open_hud(_: Principal = Depends(user)) -> dict:
        """Open the Amy HUD as a desktop webview app (not a browser tab)."""
        return {"ok": _open_hud()}

    # --- dashboard data -------------------------------------------------------------------

    @app.get("/api/system")
    def system_metrics(_: Principal = Depends(viewer)) -> dict:
        from amy.system.metrics import sample_system

        return sample_system()

    @app.get("/api/tools/catalog")
    def tools_catalog_api(category: str = "", _: Principal = Depends(viewer)) -> dict:
        from amy.tools.catalog import get_tool_catalog

        return get_tool_catalog().catalog(category)

    @app.get("/api/updates")
    def updates_api(check: bool = False, _: Principal = Depends(viewer)) -> dict:
        from amy.updates.checker import get_update_checker

        chk = get_update_checker()
        if check:
            return chk.check(force=False)
        return chk.status()

    @app.get("/api/vision/status")
    def vision_status_api(_: Principal = Depends(viewer)) -> dict:
        from amy.vision.service import get_vision_service

        return get_vision_service().status()

    @app.post("/api/vision/enroll")
    def vision_enroll_api(body: dict, _: Principal = Depends(admin)) -> dict:
        from amy.vision.service import get_vision_service

        return get_vision_service().enroll(
            str((body or {}).get("name") or ""),
            image_path=str((body or {}).get("image_path") or ""),
            from_camera=bool((body or {}).get("from_camera")),
        )

    @app.get("/api/alerts")
    def alerts_api(limit: int = Query(20, ge=1, le=200), _: Principal = Depends(viewer)) -> dict:
        from amy.workers.alerts import get_alert_bus

        return {"ok": True, "alerts": get_alert_bus().list(limit=limit)}

    # --- settings / config (admin) -----------------------------------------------------------

    @app.get("/api/settings")
    def settings_get(_: Principal = Depends(viewer)) -> dict:
        from amy.settings.store import get_settings_store

        return {"ok": True, **get_settings_store().options()}

    @app.post("/api/settings")
    def settings_set(body: dict, _: Principal = Depends(admin)) -> dict:
        from amy.settings.store import get_settings_store

        store = get_settings_store()
        snap = store.update(body or {})
        apply = getattr(host, "apply_persona", None)
        if callable(apply):
            try:
                apply(store.persona_prompt_block())
            except Exception:
                _logger.warning("could not push persona into live agent", exc_info=True)
        return {"ok": True, "settings": snap}

    @app.get("/api/integrations")
    def integrations_list(_: Principal = Depends(admin)) -> dict:
        from amy.settings.integrations import list_integrations

        return list_integrations()

    @app.post("/api/integrations/{integration_id}")
    def integrations_set(integration_id: str, body: dict, _: Principal = Depends(admin)) -> dict:
        from amy.settings.integrations import set_integration_secrets

        values = (body or {}).get("secrets") or body or {}
        if not isinstance(values, dict):
            return {"ok": False, "error": "secrets object required"}
        return set_integration_secrets(integration_id, values)

    @app.get("/api/packs")
    def packs_list(_: Principal = Depends(viewer)) -> dict:
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
    def config_studio_get(_: Principal = Depends(admin)) -> dict:
        from amy.config_studio import get_config_studio

        return get_config_studio()

    @app.post("/api/config")
    def config_studio_set(body: dict, _: Principal = Depends(admin)) -> dict:
        from amy.config_studio import update_config_studio

        return update_config_studio(body or {})

    # --- live updates ----------------------------------------------------------------------------

    def _ws_principal(websocket: WebSocket, token_q: Optional[str]) -> Optional[Principal]:
        if token_q:
            return auth.from_token(token_q)
        p = auth.from_session(websocket.cookies.get(SESSION_COOKIE))
        if p is None:
            return None
        # cookie auth: refuse cross-site WebSocket hijacking
        origin = websocket.headers.get("origin")
        if origin and urlsplit(origin).netloc != websocket.headers.get("host", ""):
            return None
        return p

    @app.websocket("/ws")
    async def ws_endpoint(
        websocket: WebSocket,
        token_q: Optional[str] = Query(None, alias="token"),
    ) -> None:
        ip = websocket.client.host if websocket.client else "?"
        if auth.throttle.blocked(ip):
            await websocket.close(code=4429)
            return
        p = _ws_principal(websocket, token_q)
        if p is None:
            auth.throttle.fail(ip)
            await websocket.close(code=4401)
            return
        if bus.watcher_count >= _MAX_WS_CLIENTS:
            await websocket.close(code=1013)
            return
        await websocket.accept()
        watcher = bus.watch()
        send_lock = asyncio.Lock()
        background: set[asyncio.Task[Any]] = set()

        async def send(msg: Dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(msg)

        async def run_turn(text: str) -> None:
            try:
                reply = await _run_turn(text)
                await send({"type": "turn_result", "ok": True, "reply": reply})
            except Exception as e:
                err = "busy" if _is_busy(e) else str(e) or type(e).__name__
                with contextlib.suppress(Exception):
                    await send({"type": "turn_result", "ok": False, "reply": "", "error": err})

        def handle(cmd: ClientCommand) -> Optional[str]:
            """Apply one client command; returns an error string when refused."""
            payload = cmd.payload or {}
            if cmd.type == "turn" and cmd.text:
                if not p.can("user"):
                    return "requires user role"
                t = asyncio.create_task(run_turn(cmd.text[:8000]))
                background.add(t)
                t.add_done_callback(background.discard)
            elif cmd.type == "approve":
                if not p.can("admin"):
                    return "requires admin role"
                g = getattr(host, "guard", None)
                aid = str(payload.get("id") or "").strip()
                if g is not None and aid:
                    g.broker.resolve(aid, bool(payload.get("approve")), via=f"hud:{p.name}")
            elif not p.can("user"):
                return "requires user role"
            elif cmd.type == "set_state" and cmd.state is not None:
                host.set_ui_state(cmd.state, detail="ws")
            elif cmd.type == "wake":
                host.trigger_wake(reason="ws")
            elif cmd.type == "barge":
                host.barge_in()
            elif cmd.type == "hive_cancel":
                tid = str(payload.get("task_id") or cmd.text or "").strip()
                if tid:
                    bus.cancel_task(tid)
            return None

        last = bus.snapshot().model_dump(mode="json")
        recv: Optional[asyncio.Task[Any]] = None
        changed: Optional[asyncio.Task[Any]] = None
        try:
            await send({"type": "snapshot", "data": last, "role": p.role})
            recv = asyncio.create_task(websocket.receive_json())
            changed = asyncio.create_task(watcher.event.wait())
            while True:
                done, _ = await asyncio.wait({recv, changed}, return_when=asyncio.FIRST_COMPLETED)
                if changed in done:
                    watcher.event.clear()
                    cur = bus.snapshot().model_dump(mode="json")
                    patch = snapshot_patch(last, cur)
                    if patch:
                        await send({"type": "patch", "data": patch})
                        last = cur
                    await asyncio.sleep(_WS_MIN_INTERVAL_S)
                    changed = asyncio.create_task(watcher.event.wait())
                if recv in done:
                    try:
                        data = recv.result()
                    except Exception:  # disconnect or malformed frame
                        break
                    recv = asyncio.create_task(websocket.receive_json())
                    try:
                        cmd = ClientCommand.model_validate(data)
                    except Exception:
                        await send({"type": "error", "error": "malformed command"})
                        continue
                    err = handle(cmd)
                    if err:
                        await send({"type": "error", "error": err, "command": cmd.type})
        except WebSocketDisconnect:
            pass
        finally:
            for t in (recv, changed, *background):
                if t is not None:
                    t.cancel()
            bus.unwatch(watcher)

    # --- static HUD ------------------------------------------------------------------------------

    if web_dist.is_dir():
        assets = web_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            # The page loads without a token; the API and socket still require one.
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
    host: Any,
    *,
    bind: str = "127.0.0.1",
    port: int = DEFAULT_SERVER_PORT,
    token: Optional[str] = None,
    lan: bool = False,
    https_port: Optional[int] = None,
) -> int:
    """Serve the HUD. With a TLS cert (``amy cert``) and ``--lan``, phones get HTTPS on
    ``https_port`` while plain HTTP stays on loopback for the local orb / webviews."""
    import uvicorn

    from amy.server.tls import resolve_tls

    tok = token or secrets.token_urlsafe(16)
    tls = resolve_tls() if lan else None
    if lan and bind in ("127.0.0.1", "localhost") and tls is None:
        bind = "0.0.0.0"  # LAN mode is an explicit opt-in

    devices = DeviceRegistry()
    app = create_app(host, token=tok, lan=lan, bind=bind, devices=devices)
    common: Dict[str, Any] = {"log_level": "info", "ws_max_size": 1_000_000, "server_header": False}

    print(f"# {ASSISTANT_NAME} server token={tok}", flush=True)
    print(f"# local link: http://127.0.0.1:{port}/?token={tok}", flush=True)
    if devices.list():
        print(f"# device tokens: {', '.join(d['name'] for d in devices.list())}", flush=True)

    if tls is None:
        if lan:
            print(f"# LAN link (phones / laptops): http://{_lan_ip()}:{port}/?token={tok}", flush=True)
            print("# tip: run `amy cert` once to serve phones over HTTPS", flush=True)
        uvicorn.run(app, host=bind, port=port, **common)
        return 0

    sport = int(https_port or os.environ.get("AMY_HTTPS_PORT") or port + 1)
    cert, key = tls
    print(f"# LAN link (HTTPS): https://{_lan_ip()}:{sport}/?token={tok}", flush=True)
    plain = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, **common))
    secure = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",  # LAN mode is an explicit opt-in
            port=sport,
            ssl_certfile=cert,
            ssl_keyfile=key,
            **common,
        )
    )

    async def _both() -> None:
        await asyncio.gather(plain.serve(), secure.serve())

    asyncio.run(_both())
    return 0
