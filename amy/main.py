"""CLI entry: python -m amy | amy run | amy serve."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from amy.branding import ASSISTANT_NAME, DEFAULT_SERVER_PORT, DEFAULT_WAKE_PHRASE
from amy.env import apply_env
from amy.logs import setup_logging

_logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="amy",
        description=f"{ASSISTANT_NAME} always-on host + LAN HUD server",
    )
    p.add_argument("--home", default=None, help="PYHIVE_HOME override")
    p.add_argument("--config", default=None, help="HIVE_CONFIG override")
    p.add_argument(
        "--log-level",
        default=None,
        help="Console log level (debug/info/warning). Full detail always goes to logs/amy.jsonl",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    def add_host_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--profile", default="ambient")
        sp.add_argument("--model", default=None)
        sp.add_argument("--wake-phrase", default=None)
        sp.add_argument("--force", action="store_true", help="Force without VCE")
        sp.add_argument("--console", action="store_true")

    def add_server_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--bind", default="127.0.0.1")
        sp.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT)
        sp.add_argument("--lan", action="store_true", help="LAN access for phones")
        sp.add_argument("--token", default=None)
        sp.add_argument(
            "--orb",
            dest="orb",
            action="store_true",
            default=True,
            help="Persistent companion orb (default on)",
        )
        sp.add_argument(
            "--no-orb",
            dest="orb",
            action="store_false",
            help="Disable companion orb",
        )
        sp.add_argument(
            "--chat-window",
            dest="chat_window",
            action="store_true",
            default=False,
            help="Open legacy captions chat window (off by default; HUD is on-demand)",
        )
        sp.add_argument(
            "--no-chat-window",
            dest="chat_window",
            action="store_false",
            help="Disable captions chat window (default)",
        )

    run = sub.add_parser("run", help="Always-on ambient voice host")
    add_host_flags(run)
    add_server_flags(run)
    run.add_argument("--serve", action="store_true", help="Also start HUD server")

    serve = sub.add_parser("serve", help="HUD/API server + ambient host")
    add_host_flags(serve)
    add_server_flags(serve)

    st = sub.add_parser("status", help="Print env / paths")
    st.add_argument("--json", action="store_true")

    apps = sub.add_parser("apps", help="Amy Apps packs (list / install / status)")
    apps_sub = apps.add_subparsers(dest="apps_cmd", required=True)
    apps_sub.add_parser("list", help="List available packs")
    apps_install = apps_sub.add_parser("install", help="Install a pack + secrets template")
    apps_install.add_argument("pack_id", help="Pack id (e.g. smartpanels)")
    apps_status = apps_sub.add_parser("status", help="Status for a pack (or all)")
    apps_status.add_argument("pack_id", nargs="?", default=None)

    doc = sub.add_parser("doctor", help="Check mic, speech, LLM, guard, HUD — what works and what doesn't")
    doc.add_argument("--json", action="store_true")
    doc.add_argument("--offline", action="store_true", help="Skip the LLM network probe")

    dev = sub.add_parser("devices", help="Per-device HUD tokens with roles (viewer/user/admin)")
    dev_sub = dev.add_subparsers(dest="devices_cmd", required=True)
    dev_add = dev_sub.add_parser("add", help="Create a token for a phone / tablet / laptop")
    dev_add.add_argument("name")
    dev_add.add_argument("--role", choices=["viewer", "user", "admin"], default="user")
    dev_rm = dev_sub.add_parser("remove", help="Revoke a device (its sessions end immediately)")
    dev_rm.add_argument("name")
    dev_sub.add_parser("list", help="List devices and roles")

    cert = sub.add_parser("cert", help="Generate a self-signed TLS certificate for HTTPS on the LAN")
    cert.add_argument("--host", action="append", default=[], help="Extra hostname / IP for the cert")
    return p


def _make_host(args: argparse.Namespace):
    from amy.host.ambient import AmbientHost
    from amy.host.events import EventBus
    from amy.storage import open_history

    return AmbientHost(
        bus=EventBus(history_store=open_history()),
        profile=getattr(args, "profile", "ambient") or "ambient",
        cwd=Path(os.environ.get("AMY_ROOT") or Path.cwd()),
        model=getattr(args, "model", None),
        wake_phrase=getattr(args, "wake_phrase", None) or DEFAULT_WAKE_PHRASE,
        force_voice=bool(getattr(args, "force", False)),
    )


def cmd_status(args: argparse.Namespace) -> int:
    root = apply_env(home=args.home, config=args.config)
    info = {
        "name": ASSISTANT_NAME,
        "amy_root": str(root),
        "PYHIVE_HOME": os.environ.get("PYHIVE_HOME"),
        "HIVE_CONFIG": os.environ.get("HIVE_CONFIG"),
        "HIVE_ARSENAL": os.environ.get("HIVE_ARSENAL"),
        "wake_phrase": os.environ.get("AMY_WAKE_PHRASE", DEFAULT_WAKE_PHRASE),
    }
    if getattr(args, "json", False):
        import json

        print(json.dumps(info, indent=2))
    else:
        for k, v in info.items():
            print(f"{k}={v}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    apply_env(home=args.home, config=args.config)
    from amy.doctor import run_cli

    return run_cli(as_json=bool(args.json), probe_network=not args.offline)


def cmd_devices(args: argparse.Namespace) -> int:
    from amy.server.auth import DeviceRegistry

    reg = DeviceRegistry()
    sub = args.devices_cmd
    if sub == "add":
        try:
            token = reg.add(args.name, role=args.role)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        port = int(os.environ.get("AMY_PORT") or DEFAULT_SERVER_PORT)
        print(f"device '{args.name}' role={args.role}")
        print(f"token (shown once): {token}")
        print(f"open on the device: http(s)://<this-pc-ip>:{port}/?token={token}")
        return 0
    if sub == "remove":
        ok = reg.remove(args.name)
        print("removed" if ok else "no such device")
        return 0 if ok else 1
    devices = reg.list()
    if not devices:
        print("no devices — add one with: amy devices add phone --role user")
    for d in devices:
        print(f"{d['name']}\t{d['role']}")
    return 0


def cmd_cert(args: argparse.Namespace) -> int:
    from amy.server.tls import generate_self_signed

    try:
        cert, key = generate_self_signed(hosts=list(args.host or []))
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"cert: {cert}\nkey:  {key}")
    print("amy serve picks these up automatically and serves https:// (phones will warn once).")
    return 0


def cmd_apps(args: argparse.Namespace) -> int:
    apply_env(home=args.home, config=args.config)
    from amy.apps.loader import enabled_pack_ids, get_pack, install_pack, list_packs
    from amy.apps.secrets import secrets_path, secrets_present

    sub = getattr(args, "apps_cmd", None)
    if sub == "list":
        enabled = {x.lower() for x in enabled_pack_ids()}
        packs = list_packs()
        if not packs:
            print("No packs found under apps/packs/")
            return 0
        for p in packs:
            mark = "enabled" if p["id"].lower() in enabled else "available"
            print(f"{p['id']}\t{mark}\t{p.get('name') or ''}\t{p['path']}")
        return 0

    if sub == "install":
        pid = (args.pack_id or "").strip()
        result = install_pack(pid)
        if not result.get("ok"):
            print(f"error: {result.get('error')}", file=sys.stderr)
            return 1
        print(f"installed {result['id']}")
        print(f"secrets: {result['secrets']}")
        print("Fill SMARTPANELS_USER / SMARTPANELS_PASSWORD (CLI only — never via voice).")
        print("Enable in config/hive.yaml → amy.apps.enabled if not already listed.")
        return 0

    if sub == "status":
        pid = (getattr(args, "pack_id", None) or "").strip()
        enabled = enabled_pack_ids()
        targets = [pid] if pid else [p["id"] for p in list_packs()]
        if not targets:
            print("No packs found.")
            return 0
        for tid in targets:
            pack = get_pack(tid)
            if not pack:
                print(f"{tid}: unknown")
                continue
            man = pack.get("manifest") or {}
            keys = list((man.get("secrets") or {}).get("keys") or [])
            req = [k for k in keys if k.endswith("_USER") or k.endswith("_PASSWORD")]
            if not req and keys:
                req = keys[:2]
            present = secrets_present(tid, req) if req else secrets_path(tid).is_file()
            en = tid.lower() in {x.lower() for x in enabled}
            print(
                f"{tid}: enabled={en} secrets_present={present} "
                f"secrets_file={secrets_path(tid)}"
            )
            if tid.lower() == "smartpanels":
                try:
                    import importlib.util
                    import sys as _sys

                    cpath = pack["path"] / "client.py"
                    pdir = str(pack["path"])
                    if pdir not in _sys.path:
                        _sys.path.insert(0, pdir)
                    spec = importlib.util.spec_from_file_location(
                        "amy_pack_smartpanels_client_cli", cpath
                    )
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        st = mod.status()
                        print(
                            f"  session_valid={st.get('session_valid')} "
                            f"reachable={st.get('reachable')} via={st.get('via') or '-'}"
                        )
                except Exception as e:
                    print(f"  (status probe failed: {e})")
        return 0

    print("usage: amy apps list|install|status", file=sys.stderr)
    return 2


def _wait_http(host: str, port: int, *, timeout: float = 30.0) -> bool:
    from amy.host.browsers import wait_for_http

    return wait_for_http(f"http://{host}:{port}/", timeout=timeout, interval=0.2)


def _run_with_server(host, args: argparse.Namespace) -> int:
    import secrets

    from amy.host.chat_bridge import ChatBridge
    from amy.host.orb_bridge import OrbBridge
    from amy.server.app import run_server

    stop = threading.Event()
    orb: OrbBridge | None = None
    chat: ChatBridge | None = None
    token = args.token or secrets.token_urlsafe(16)
    os.environ["AMY_TOKEN"] = token
    # Frameless pywebview orb — never Edge/Chrome title-bar chrome by default.
    if (os.environ.get("AMY_ORB_MODE") or "").strip().lower() in ("", "auto", "chromium", "browser"):
        os.environ["AMY_ORB_MODE"] = "webview"
    bind = args.bind
    port = int(args.port)
    os.environ["AMY_PORT"] = str(port)
    os.environ.setdefault("AMY_HOST", "127.0.0.1")
    # Orb always talks to loopback HUD even when server binds 0.0.0.0
    orb_host = "127.0.0.1"
    server_error: list[BaseException] = []

    def _boot() -> None:
        try:
            host.start()
        except Exception as e:
            print(f"# amy host start failed: {e}", flush=True)
            stop.set()

    def _serve() -> None:
        try:
            run_server(
                host,
                bind=bind,
                port=port,
                token=token,
                lan=bool(args.lan),
            )
        except BaseException as e:
            server_error.append(e)
            print(f"# amy server exited: {e}", flush=True)
        finally:
            stop.set()

    # HUD first (so orb/captions don't wait on a dead port), voice host in parallel.
    threading.Thread(target=_boot, name="amy-host-start", daemon=True).start()
    srv = threading.Thread(target=_serve, name="amy-hud-server", daemon=True)
    srv.start()

    if not _wait_http(orb_host, port, timeout=45.0):
        print("# amy HUD server did not come up — skipping companion windows", flush=True)
    else:
        print(f"# amy HUD ready http://{orb_host}:{port}/", flush=True)
        want_orb = bool(getattr(args, "orb", True))
        # Production: orb-only companion. Full HUD opens on demand from launcher.
        # Opt in with --chat-window or AMY_CHAT_WINDOW=1.
        env_chat = os.environ.get("AMY_CHAT_WINDOW", "").strip().lower()
        if env_chat in ("1", "true", "yes", "on"):
            want_chat = True
        elif env_chat in ("0", "false", "no", "off"):
            want_chat = False
        else:
            want_chat = bool(getattr(args, "chat_window", False))

        if want_orb:
            orb = OrbBridge(
                host.bus,
                token=token,
                host=orb_host,
                port=port,
                enabled=True,
            )
            if not orb.start():
                print("# amy orb failed to start", flush=True)
                orb = None

        if want_chat:
            chat = ChatBridge(
                host.bus,
                token=token,
                host=orb_host,
                port=port,
                enabled=True,
            )
            if chat.start():
                print(
                    f"# amy captions HUD (right) → "
                    f"http://{orb_host}:{port}/?view=chat",
                    flush=True,
                )
            else:
                print("# amy captions chat window failed to start", flush=True)
                chat = None

    def _on_sig(*_a) -> None:
        if chat:
            chat.stop()
        if orb:
            orb.stop()
        host.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _on_sig)
    try:
        signal.signal(signal.SIGTERM, _on_sig)
    except Exception:
        _logger.debug("ignored error", exc_info=True)

    if getattr(args, "console", False):

        def _console() -> None:
            try:
                while not stop.is_set():
                    try:
                        line = input("you> ").strip()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if not line or line in {"/exit", "/quit"}:
                        break
                    if line == "/wake":
                        host.trigger_wake("console")
                        continue
                    print(f"amy> {host.turn_text(line)}", flush=True)
            finally:
                stop.set()

        threading.Thread(target=_console, name="amy-console", daemon=True).start()

    try:
        while srv.is_alive() and not stop.is_set():
            srv.join(timeout=0.5)
        return 1 if server_error else 0
    finally:
        if chat:
            chat.stop()
        if orb:
            orb.stop()
        host.stop()


def cmd_run(args: argparse.Namespace) -> int:
    apply_env(home=args.home, config=args.config)
    host = _make_host(args)
    if args.serve or args.lan:
        return _run_with_server(host, args)
    return host.run_forever(console=bool(args.console))


def cmd_serve(args: argparse.Namespace) -> int:
    apply_env(home=args.home, config=args.config)
    host = _make_host(args)
    return _run_with_server(host, args)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        raw = ["run"]
    elif raw[0] not in {
        "run", "serve", "status", "apps", "doctor", "devices", "cert", "-h", "--help",
    }:
        raw = ["run", *raw]

    args = build_parser().parse_args(raw)
    if args.cmd in ("run", "serve"):
        apply_env(home=args.home, config=args.config)
        setup_logging(level=args.log_level)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "doctor":
        return cmd_doctor(args)
    if args.cmd == "devices":
        return cmd_devices(args)
    if args.cmd == "cert":
        return cmd_cert(args)
    if args.cmd == "apps":
        return cmd_apps(args)
    if args.cmd == "serve":
        return cmd_serve(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
