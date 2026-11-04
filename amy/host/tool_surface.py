"""Start-up wiring of the agent's tool surface: product config, tools, hive, safety guard."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from amy.hive_adapter import HiveAdapter
from amy.host.events import EventBus

_logger = logging.getLogger(__name__)

Log = Callable[[str], None]


@dataclass
class HomeRegion:
    label: str = ""
    tz: str = ""
    city: str = ""


def load_amy_yaml() -> Dict[str, Any]:
    """The ``amy:`` section of HIVE_CONFIG (empty when missing or unreadable)."""
    path = os.environ.get("HIVE_CONFIG") or ""
    if not path or not Path(path).is_file():
        return {}
    try:
        import yaml

        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:
        _logger.warning("could not read %s", path, exc_info=True)
        return {}
    amy = raw.get("amy") if isinstance(raw, dict) else None
    return amy if isinstance(amy, dict) else {}


def home_region(amy_cfg: Dict[str, Any]) -> HomeRegion:
    home = amy_cfg.get("home") or {}
    if not isinstance(home, dict) or not home:
        return HomeRegion()
    label = str(
        home.get("label")
        or ", ".join(
            str(home.get(k) or "").strip()
            for k in ("city", "region", "country")
            if str(home.get(k) or "").strip()
        )
    ).strip()
    if not label:
        return HomeRegion()
    return HomeRegion(
        label=label,
        tz=str(home.get("timezone") or "").strip(),
        city=str(home.get("city") or "").strip(),
    )


def home_prompt_block(home: HomeRegion) -> str:
    return (
        f"\n\nHOME REGION: {home.label}"
        + (f" ({home.tz})" if home.tz else "")
        + ". For weather / local asks without a city, "
        "use THIS region — never invent Delhi or another city. "
        "Prefer one focused query like "
        f"'current weather {home.label} today'."
    )


def apply_product_config(hive: HiveAdapter, bus: EventBus, log: Log) -> HomeRegion:
    """Push Bambu / slicer / local-app / updates / home settings into tools and the agent."""
    from amy.tools.bambu import apply_config as apply_bambu
    from amy.tools.local_apps import apply_config as apply_local_apps
    from amy.tools.slicer import apply_config as apply_slicer

    hcfg = hive.hive_config
    apply_bambu(hcfg)
    apply_slicer(hcfg)
    apply_local_apps(hcfg if isinstance(hcfg, dict) else {})

    amy_cfg = load_amy_yaml()
    if not amy_cfg:
        return HomeRegion()
    apply_bambu(amy_cfg)
    apply_slicer(amy_cfg)
    apply_local_apps(amy_cfg)
    try:
        from amy.updates.checker import get_update_checker

        upd = amy_cfg.get("updates")
        get_update_checker(upd if isinstance(upd, dict) else {})
    except Exception:
        _logger.warning("update checker config failed", exc_info=True)

    home = home_region(amy_cfg)
    if not home.label:
        return home
    os.environ["AMY_HOME_LABEL"] = home.label
    if home.tz:
        os.environ["AMY_HOME_TZ"] = home.tz
    if home.city:
        os.environ["AMY_HOME_CITY"] = home.city
    hive.append_prompt_block_once("HOME REGION:", home_prompt_block(home))
    raw_home = amy_cfg.get("home") or {}
    hive.set_service("amy_home", dict(raw_home))
    hive.set_service("amy_home_label", home.label)
    bus.note_activity(home.label.split(",")[0].strip() or "home", kind="weather", detail=home.label)
    log(f"home region={home.label}")
    return home


def setup_tools(hive: HiveAdapter, bus: EventBus, log: Log) -> Dict[str, Any]:
    """Register Amy tools + hive_delegate, prune to the active catalog, publish to the HUD."""
    from amy.apps.registry_hook import merge_allowlist_keep
    from amy.hive import register_hive_delegate_tools
    from amy.tools import AMY_TOOL_ALLOWLIST, prune_registry_to_allowlist, setup_amy_tool_surface

    reg = hive.registry
    if reg is None:
        log("no tool registry — agent runs without tools")
        return {}
    hcfg = hive.hive_config
    info = setup_amy_tool_surface(reg, config=hcfg)

    def _hive_activity(agent_id: str, detail: str) -> None:
        bus.note_activity(f"hive:{agent_id}", kind="agent", detail=detail)

    try:
        def _register_hive() -> List[str]:
            return register_hive_delegate_tools(
                reg, shell=hive.shell, bus=bus, on_log=log, on_activity=_hive_activity
            )

        _register_hive()
        allow = merge_allowlist_keep(list(AMY_TOOL_ALLOWLIST), config=hcfg)
        prune_registry_to_allowlist(reg, allowlist=allow)
        # prune drops hive_delegate (not in the base allowlist); bind it again
        info["hive"] = _register_hive()
        log(f"hive tools={info['hive']}")
    except Exception as e:
        log(f"hive register: {e}")
        _logger.warning("hive_delegate registration failed", exc_info=True)

    kept = sorted({getattr(t, "name", "") for t in reg.list_tools() if getattr(t, "name", "")})
    info["kept"] = kept
    log(
        f"tools amy={info.get('amy')} apps={info.get('apps')} "
        f"hive={info.get('hive')} voice={info.get('voice')} kept={kept}"
    )
    try:
        names = merge_allowlist_keep(list(AMY_TOOL_ALLOWLIST), config=hcfg)
        bus.set_tools(names)
        bus.note_activity("ready", kind="status", detail=f"{len(names)} tools")
    except Exception:
        _logger.warning("could not publish tool list", exc_info=True)
        if kept:
            bus.set_tools(kept)
    return info


def install_guard(
    hive: HiveAdapter,
    bus: EventBus,
    log: Log,
    *,
    voice_approver: Optional[Callable[[str], Optional[bool]]] = None,
) -> Any:
    """Put the safety policy in front of every agent tool. Fails closed.

    Returns the installed Guard, or None when ``amy.guard.enabled`` is false.
    """
    from amy.guard import Guard, load_guard_config, set_guard
    from amy.guard.policy import READ_ONLY_TOOLS
    from amy.logs import set_redactor
    from amy.tools.voice_host import VOICE_HOST_ALLOWLIST

    reg = hive.registry
    cfg = load_guard_config()
    if not cfg.enabled:
        log("WARNING: amy.guard.enabled=false — agent tools run with NO safety policy")
        _logger.warning("safety guard disabled by config")
        return None
    guard = Guard(cfg, bus=bus, on_log=lambda m: log(f"guard {m}"))
    tok = os.environ.get("AMY_TOKEN") or ""
    if tok:
        guard.redactor.add_literal(tok)
    set_redactor(guard.redactor.text)
    set_guard(guard)
    if voice_approver is not None:
        guard.broker.voice_approver = voice_approver
    if reg is None:
        return guard

    try:
        report = guard.install(reg, exempt=VOICE_HOST_ALLOWLIST)
        log(
            f"guard mode={cfg.mode} lockdown={cfg.lockdown} "
            f"wrapped={len(report['inplace']) + len(report['reregistered'])} "
            f"removed={report['removed']} unwrapped={report['unwrapped']}"
        )
    except Exception as e:
        log(f"guard install failed ({e}) — removing every tool with side effects")
        _logger.error("guard install failed", exc_info=True)
        keep = set(READ_ONLY_TOOLS) | set(VOICE_HOST_ALLOWLIST)
        for t in list(reg.list_tools()):
            name = getattr(t, "name", "")
            if name and name not in keep:
                try:
                    reg.unregister(name)
                except Exception:
                    _logger.error("could not remove unguarded tool %s", name, exc_info=True)

    # tools_activate re-registers raw tool functions; re-wrap after every change.
    try:
        from amy.tools.catalog import get_tool_catalog

        cat = get_tool_catalog()
        reprune = cat._reprune

        def _reprune_guarded() -> None:
            reprune()
            guard.install(reg, exempt=VOICE_HOST_ALLOWLIST)

        cat._reprune = _reprune_guarded  # type: ignore[method-assign]
    except Exception as e:
        log(f"guard catalog hook failed ({e}) — disabling tools_activate")
        _logger.error("guard catalog hook failed", exc_info=True)
        try:
            reg.unregister("tools_activate")
        except Exception:
            _logger.error("could not remove tools_activate", exc_info=True)
    return guard
