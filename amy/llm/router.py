"""Local OpenAI/Ollama-compatible proxy that sends each request to the best healthy backend.

PyHive points at ``http://127.0.0.1:<port>/v1``; the router rewrites the ``model`` field for
whichever backend serves the request, retries on the next backend if one is unreachable
before it answers, and switches back to a preferred backend only after it has been healthy
for ``recover_after`` probes in a row.
"""

from __future__ import annotations

import http.client
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

from amy.llm.config import Backend, RoutingConfig
from amy.llm.tunnel import SshTunnel

_logger = logging.getLogger(__name__)

_MAX_BODY = 64 * 1024 * 1024
_HOP_HEADERS = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
    "trailer", "transfer-encoding", "upgrade", "content-length", "host",
})
# Statuses that mean "try another backend" when one is left (model missing, overloaded, down).
_RETRY_STATUSES = frozenset({404, 500, 502, 503, 504})


@dataclass
class BackendHealth:
    healthy: bool = False
    ok_streak: int = 0
    fail_streak: int = 0
    last_error: str = "not checked yet"
    latency_ms: Optional[float] = None
    checked_at: float = 0.0
    requests: int = 0
    failures: int = 0


def _model_names(body: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for m in body.get("models") or []:
        if isinstance(m, dict):
            names += [str(m.get(k)) for k in ("name", "model") if m.get(k)]
    for m in body.get("data") or []:
        if isinstance(m, dict) and m.get("id"):
            names.append(str(m["id"]))
    return names


def _has_model(names: List[str], model: str) -> bool:
    want = {model, model + ":latest", model.removesuffix(":latest")}
    return any(n in want for n in names)


def rewrite_model(body: bytes, model: str) -> bytes:
    """Replace the JSON ``model`` field (leaves non-JSON or model-less bodies alone)."""
    if not body or b'"model"' not in body:
        return body
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if isinstance(data, dict) and "model" in data:
        data["model"] = model
        return json.dumps(data).encode("utf-8")
    return body


class LlmRouter:
    def __init__(
        self,
        cfg: RoutingConfig,
        *,
        tunnels: Optional[Dict[str, SshTunnel]] = None,
        manage_tunnels: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.backends = list(cfg.backends)
        self.clock = clock
        self.tunnels: Dict[str, SshTunnel] = dict(tunnels or {})
        if manage_tunnels:
            for b in self.backends:
                if b.ssh is not None and b.name not in self.tunnels:
                    self.tunnels[b.name] = SshTunnel(b.ssh)
        self.health: Dict[str, BackendHealth] = {b.name: BackendHealth() for b in self.backends}
        self._active: Optional[str] = None
        self._pinned: Optional[str] = None
        self._lock = threading.RLock()
        self._listeners: List[Callable[[Optional[Backend], Optional[Backend]], None]] = []
        self._stop = threading.Event()
        self._server: Optional[ThreadingHTTPServer] = None
        self._threads: List[threading.Thread] = []

    # --- public ----------------------------------------------------------------------

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else self.cfg.port

    @property
    def base_url(self) -> str:
        return f"http://{self.cfg.host}:{self.port}/v1"

    def on_switch(self, fn: Callable[[Optional[Backend], Optional[Backend]], None]) -> None:
        self._listeners.append(fn)

    def backend(self, name: str) -> Optional[Backend]:
        return next((b for b in self.backends if b.name == name), None)

    def active(self) -> Optional[Backend]:
        with self._lock:
            return self.backend(self._active) if self._active else None

    def pin(self, name: Optional[str]) -> None:
        """Force one backend (``None`` = automatic)."""
        if name is not None and self.backend(name) is None:
            raise KeyError(name)
        with self._lock:
            self._pinned = name
        self._reselect(force=True)

    def start(self, *, serve: bool = True) -> LlmRouter:
        self.probe_all()
        if serve:
            self._server = ThreadingHTTPServer((self.cfg.host, self.cfg.port), _handler_for(self))
            self._server.daemon_threads = True
            t = threading.Thread(target=self._server.serve_forever, name="amy-llm-router", daemon=True)
            t.start()
            self._threads.append(t)
        m = threading.Thread(target=self._monitor, name="amy-llm-probe", daemon=True)
        m.start()
        self._threads.append(m)
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        for t in self.tunnels.values():
            t.stop()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            act = self.active()
            primary = self.backends[0].name if self.backends else None
            return {
                "active": act.name if act else None,
                "label": act.display if act else "no model reachable",
                "model": act.model if act else "",
                "fallback": bool(act and act.name != primary),
                "pinned": self._pinned,
                "base_url": self.base_url,
                "backends": [
                    {
                        "name": b.name,
                        "label": b.display,
                        "model": b.model,
                        "via": "ssh" if b.ssh else b.base_url,
                        "healthy": self.health[b.name].healthy,
                        "latency_ms": self.health[b.name].latency_ms,
                        "error": "" if self.health[b.name].healthy else self.health[b.name].last_error,
                        "requests": self.health[b.name].requests,
                    }
                    for b in self.backends
                ],
            }

    # --- health --------------------------------------------------------------------------

    def probe(self, b: Backend) -> Tuple[bool, str, Optional[float]]:
        tunnel = self.tunnels.get(b.name)
        if tunnel is not None and not tunnel.ensure():
            return False, tunnel.last_error or "ssh tunnel down", None
        t0 = time.perf_counter()
        last = ""
        for path in ("/api/tags", "/v1/models"):
            try:
                with urllib.request.urlopen(b.base_url + path, timeout=self.cfg.probe_timeout_s) as r:
                    body = json.loads(r.read(2_000_000) or b"{}")
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code} on {path}"
                continue
            except (urllib.error.URLError, OSError, ValueError) as e:
                return False, str(getattr(e, "reason", e))[:160], None
            ms = round((time.perf_counter() - t0) * 1000, 1)
            if not _has_model(_model_names(body), b.model):
                return False, f"model {b.model} not installed there", ms
            return True, "", ms
        return False, last or "no model list", None

    def probe_all(self) -> None:
        for b in self.backends:
            ok, err, ms = self.probe(b)
            self._record(b.name, ok, err, ms)
        self._reselect()

    def report_failure(self, b: Backend, err: str) -> None:
        with self._lock:
            h = self.health[b.name]
            h.failures += 1
        self._record(b.name, False, err, None)
        self._reselect()

    def _record(self, name: str, ok: bool, err: str, ms: Optional[float]) -> None:
        with self._lock:
            h = self.health[name]
            h.checked_at = self.clock()
            h.latency_ms = ms if ok else h.latency_ms
            if ok:
                h.ok_streak += 1
                h.fail_streak = 0
                h.healthy = True
                h.last_error = ""
            else:
                h.ok_streak = 0
                h.fail_streak += 1
                h.healthy = False
                h.last_error = err

    def _choose(self, force: bool = False) -> Optional[str]:
        """Best healthy backend; ``force`` skips the recovery wait (manual changes)."""
        with self._lock:
            if self._pinned and self.health[self._pinned].healthy:
                return self._pinned
            current = self._active
            cur_idx = next((i for i, b in enumerate(self.backends) if b.name == current), None)
            cur_ok = not force and current is not None and self.health[current].healthy
            for i, b in enumerate(self.backends):
                h = self.health[b.name]
                if not h.healthy:
                    continue
                # leave a working fallback only once the preferred backend has proven stable
                if cur_ok and cur_idx is not None and i < cur_idx and h.ok_streak < self.cfg.recover_after:
                    continue
                return b.name
            return None

    def _reselect(self, force: bool = False) -> None:
        with self._lock:
            prev = self._active
            nxt = self._choose(force)
            if nxt == prev:
                return
            self._active = nxt
        old, new = (self.backend(prev) if prev else None), (self.backend(nxt) if nxt else None)
        _logger.info("llm backend %s -> %s", prev, nxt)
        for fn in list(self._listeners):
            try:
                fn(old, new)
            except Exception:
                _logger.warning("llm switch listener failed", exc_info=True)

    def _monitor(self) -> None:
        while not self._stop.wait(self.cfg.probe_interval_s):
            try:
                self.probe_all()
            except Exception:
                _logger.error("llm probe failed", exc_info=True)

    # --- proxying ------------------------------------------------------------------------

    def connect_timeout(self, b: Backend) -> float:
        """Loopback connects finish in well under a millisecond, but Windows takes ~2 s to
        refuse one on a closed port; a short limit makes failover fast. LAN hosts get longer."""
        host = b.host_port[0]
        if host in ("127.0.0.1", "localhost", "::1"):
            return 0.5
        return self.cfg.probe_timeout_s + 2

    def candidates(self) -> List[Backend]:
        """Active backend first, then other healthy ones, then the rest (last resort)."""
        with self._lock:
            act = self.active()
            healthy = [b for b in self.backends if self.health[b.name].healthy and b is not act]
            rest = [b for b in self.backends if not self.health[b.name].healthy and b is not act]
        return ([act] if act else []) + healthy + rest


def _handler_for(router: LlmRouter) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"
        server_version = "amy-llm-router"

        def log_message(self, fmt: str, *args: Any) -> None:
            _logger.debug("router: " + fmt, *args)

        def do_GET(self) -> None:
            self._proxy()

        def do_POST(self) -> None:
            self._proxy()

        def do_DELETE(self) -> None:
            self._proxy()

        def do_HEAD(self) -> None:
            self._proxy()

        def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _proxy(self) -> None:
            if self.path.startswith("/__amy/status"):
                self._send_json(200, router.status())
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > _MAX_BODY:
                self._send_json(413, {"error": "request too large"})
                return
            body = self.rfile.read(length) if length else b""
            headers = {k: v for k, v in self.headers.items() if k.lower() not in _HOP_HEADERS}
            tried: List[str] = []
            cands = router.candidates()
            for i, b in enumerate(cands):
                last_chance = i == len(cands) - 1
                payload = rewrite_model(body, b.model)
                host, port = b.host_port
                conn = http.client.HTTPConnection(host, port, timeout=router.connect_timeout(b))
                try:
                    conn.connect()
                    if conn.sock is not None:
                        conn.sock.settimeout(router.cfg.request_timeout_s)
                    conn.request(self.command, self.path, body=payload or None,
                                 headers={**headers, "Content-Length": str(len(payload))})
                    resp = conn.getresponse()
                except (OSError, http.client.HTTPException) as e:
                    conn.close()
                    tried.append(f"{b.name}: {e}")
                    router.report_failure(b, f"request failed: {e}"[:160])
                    continue
                if resp.status in _RETRY_STATUSES and not last_chance:
                    detail = resp.read(4000).decode("utf-8", "replace")
                    conn.close()
                    tried.append(f"{b.name}: HTTP {resp.status}")
                    router.report_failure(b, f"HTTP {resp.status}: {detail[:120]}")
                    continue
                with router._lock:
                    router.health[b.name].requests += 1
                try:
                    self.send_response(resp.status)
                    for k, v in resp.getheaders():
                        if k.lower() not in _HOP_HEADERS:
                            self.send_header(k, v)
                    self.send_header("X-Amy-Backend", b.name)
                    self.end_headers()
                    if self.command != "HEAD":
                        while True:
                            chunk = resp.read1(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    _logger.debug("client went away mid-response")
                finally:
                    conn.close()
                return
            self._send_json(503, {"error": "no model backend reachable", "tried": tried})

    return Handler
