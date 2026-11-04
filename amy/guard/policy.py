"""Per-tool risk rules. Pure: no I/O besides DNS lookups for URL checks."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from amy.guard.config import GuardConfig
from amy.guard.paths import check_path, is_sensitive, resolve
from amy.guard.shell import classify_command
from amy.guard.urls import check_url

_RANK = {"allow": 0, "confirm": 1, "deny": 2}
_RISK_RANK = {"low": 0, "medium": 1, "high": 2}

# Tools whose output is attacker-controllable text (web pages, search hits,
# specialist summaries of them). After one runs, risky actions need a human.
TAINT_TOOLS = frozenset({"web_search", "web_fetch", "hive_delegate"})

# Tools that may still run in lockdown / background (read-only, no side effects).
READ_ONLY_TOOLS = frozenset({
    "os_process_list", "bambu_status", "slicer_find", "smartpanels_status",
    "smartpanels_rooms", "web_search", "read_file", "list_dir",
    "tools_catalog", "os_active_window", "os_list_apps", "reg_query", "reg_list",
    "reg_search", "reg_analyze_app", "local_app_list", "local_app_status",
    "vision_status", "vision_list_people", "updates_status",
})

# Registry locations used for persistence, security bypass or credential theft.
_REG_DENY_RE = re.compile(
    r"\\(sam|security)(\\|$)"
    r"|currentversion\\(run|runonce|runservices|policies\\explorer\\run)"
    r"|winlogon|image file execution options|silentprocessexit|appinit_dlls|appcertdlls"
    r"|\\control\\lsa|\\control\\safeboot|\\services\\"
    r"|windows defender|\\policies\\microsoft\\windows\\(system|safer|windowsupdate)"
    r"|\\shell\\[^\\]+\\command|\\shellex|\\inprocserver32|\\localserver32|\\treatas"
    r"|\\environment(\\|$)|\\session manager"
    r"|simontatham\\putty\\sessions|martin prikryl|\\credentials",
    re.I,
)
_REG_READ_DENY_RE = re.compile(r"(^|\\)(sam|security)(\\|$)|\\control\\lsa\\secrets", re.I)
_LOLBINS = frozenset({
    "mshta", "regsvr32", "rundll32", "cscript", "wscript", "installutil", "msbuild",
    "certutil", "bitsadmin", "msiexec", "regedit", "reg", "schtasks", "sc", "net",
    "diskpart", "bcdedit", "vssadmin", "wmic", "msdt",
})

_PROTECTED_PROCESSES = frozenset({
    "system", "idle", "registry", "csrss", "wininit", "winlogon", "services",
    "lsass", "lsaiso", "smss", "svchost", "explorer", "dwm", "fontdrvhost",
    "sihost", "msmpeng", "nissrv", "securityhealthservice", "securityhealthsystray",
    "mpdefendercoreservice", "wscsvc", "python", "pythonw", "py", "ffplay",
})
_PROCESS_NAME_RE = re.compile(r"^[A-Za-z0-9._ \-]{1,64}$")

_APP_ALIASES = frozenset({
    "chrome", "edge", "firefox", "notepad", "explorer", "terminal", "settings",
    "calculator", "display", "sound",
})
_SHELL_APPS = frozenset({"cmd", "powershell", "pwsh", "wt", "terminal"})
_SCRIPT_EXTS = frozenset({
    ".ps1", ".psm1", ".bat", ".cmd", ".vbs", ".vbe", ".js", ".jse", ".wsf",
    ".hta", ".scr", ".msi", ".msp", ".reg", ".lnk", ".pif", ".com", ".cpl", ".jar",
})
_MODEL_EXTS = frozenset({".stl", ".3mf", ".obj", ".step", ".stp", ".amf", ".ply"})

_COMMAND_KEYS = ("command", "cmd", "script", "code", "commands", "line")
_PATH_KEYS = ("path", "file", "file_path", "filepath", "filename", "dir", "directory",
              "folder", "root", "target", "pattern")


@dataclass
class Decision:
    action: str  # allow | confirm | deny
    reason: str
    summary: str
    risk: str = "low"
    args_override: Dict[str, Any] = field(default_factory=dict)

    def escalate(self, action: str, reason: str) -> "Decision":
        if _RANK[action] > _RANK[self.action]:
            self.action = action
            self.reason = reason
        return self


def _s(args: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _first_str(args: Dict[str, Any], keys) -> str:
    v = _s(args, *keys)
    if v:
        return v
    for x in args.get("_args") or ():
        if isinstance(x, str) and x.strip():
            return x.strip()
    return ""


def _short(v: str, n: int = 120) -> str:
    v = " ".join((v or "").split())
    return v if len(v) <= n else v[: n - 1] + "…"


Rule = Callable[[Dict[str, Any], GuardConfig], Decision]


def _low(summary: str) -> Decision:
    return Decision("allow", "low-impact action", summary, "low")


def _r_volume(a, c):
    return _low(f"set volume {a.get('level') if a.get('level') is not None else a.get('delta')}")


def _r_toggle(a, c):
    feat = str(a.get("feature") or "").lower().replace("-", "_").replace(" ", "_")
    if feat in ("wifi", "wi_fi") and a.get("enabled") is not True:
        return Decision("confirm", "turning Wi-Fi off cuts Amy's network and model", "turn Wi-Fi off", "medium")
    return _low(f"toggle {feat or '?'}")


def _r_open_app(a, c):
    name = _s(a, "name").lower()
    path = _s(a, "path")
    target = path or name
    if not target:
        return _low("open app")
    if not path and name in _APP_ALIASES:
        return _low(f"open {name}")
    stem = Path(target).stem.lower()
    if name in _SHELL_APPS or stem in _SHELL_APPS:
        return Decision("confirm", "opens a command shell", f"open {target}", "high")
    if stem in _LOLBINS or name.removesuffix(".exe") in _LOLBINS:
        return Decision("deny", "system tool that can run arbitrary code", f"open {target}", "high")
    if not path and re.fullmatch(r"[\w .+\-]{1,60}", name) and not Path(name).suffix.lower() in _SCRIPT_EXTS:
        return Decision("allow", "opens an installed app by name", f"open {name}", "medium")
    try:
        p = resolve(target, Path.cwd())
        if p.suffix.lower() in _SCRIPT_EXTS:
            return Decision("deny", f"launching {p.suffix} files can run arbitrary code", f"open {target}", "high")
        if is_sensitive(p):
            return Decision("deny", "path holds secrets or credentials", f"open {target}", "high")
    except Exception:
        pass
    if re.match(r"^[a-z][a-z0-9+.\-]*:", target, re.I) and not target.lower().startswith("ms-settings:") \
            and not re.match(r"^[a-z]:[\\/]", target, re.I):
        return Decision("deny", "protocol handlers can launch arbitrary programs", f"open {target}", "high")
    return Decision("confirm", "launches a program that is not on the known list", f"open {_short(target)}", "medium")


def _r_browse(a, c):
    url = _s(a, "url")
    if not url:
        return _low(f"web search {_short(_s(a, 'query'), 60)}")
    verdict, why = check_url(url, purpose="browse", allow_private=c.fetch_allow_private)
    return Decision(verdict, why, f"open {_short(url)}", "low" if verdict == "allow" else "medium")


def _r_fetch(a, c):
    url = _first_str(a, ("url", "uri", "link", "href"))
    if not url:
        return _low("fetch page")
    verdict, why = check_url(url, purpose="fetch", allow_private=c.fetch_allow_private)
    return Decision(verdict, why, f"fetch {_short(url)}", "low" if verdict == "allow" else "high")


def _r_power(a, c):
    act = str(a.get("action") or "shutdown").strip().lower().replace("-", "_").replace(" ", "_")
    if act in ("lock", "lock_workstation", "cancel", "abort", "cancel_shutdown", "abort_shutdown"):
        return _low(f"power {act}")
    if act in ("sleep", "suspend"):
        return Decision("confirm", "puts the PC to sleep", "put the PC to sleep", "medium")
    delay = a.get("delay_seconds")
    try:
        delay = 60 if delay is None else int(delay)
    except Exception:
        delay = 60
    override = {"delay_seconds": max(60, delay)}
    label = "restart" if act in ("restart", "reboot") else "shut down"
    return Decision(
        "confirm",
        "closes all apps and may lose unsaved work",
        f"{label} the PC in {override['delay_seconds']} seconds",
        "high",
        args_override=override,
    )


def _r_kill(a, c):
    pid = a.get("pid")
    name = _s(a, "name")
    if pid not in (None, ""):
        try:
            pid_i = int(pid)
        except Exception:
            return Decision("deny", "pid must be a number", "kill process", "high")
        if pid_i in (os.getpid(), os.getppid()) or pid_i <= 4:
            return Decision("deny", "refusing to kill Amy or a system process", f"kill pid {pid_i}", "high")
        return Decision("confirm", "killing by pid cannot be checked against the protected list",
                        f"kill process id {pid_i}", "medium")
    if not name or not _PROCESS_NAME_RE.match(name):
        return Decision("deny", "invalid process name", f"kill {_short(name, 40)}", "high")
    base = name.lower().removesuffix(".exe").strip()
    if base in _PROTECTED_PROCESSES:
        return Decision("deny", f"{base} is a protected process", f"kill {name}", "high")
    return Decision("allow", "closes a user app", f"kill {name}", "medium")


def _r_shell(a, c):
    if not c.allow_shell:
        return Decision("deny", "shell access is disabled in amy.guard", "run a shell command", "high")
    cmd = _first_str(a, _COMMAND_KEYS)
    if not cmd and isinstance(a.get("commands"), list):
        cmd = "; ".join(str(x) for x in a["commands"])
    if not cmd:
        return Decision("deny", "could not find the command to check", "run a shell command", "high")
    verdict, why = classify_command(cmd)
    risk = {"allow": "low", "confirm": "high", "deny": "high"}[verdict]
    return Decision(verdict, why, f"run: {_short(cmd, 140)}", risk)


def _r_files(a, c):
    path = _first_str(a, _PATH_KEYS)
    verdict, why = check_path(path, c.read_roots)
    return Decision(verdict, why, f"read {_short(path or '.', 100)}", "low" if verdict == "allow" else "high")


def _r_bambu_status(a, c):
    host = _s(a, "host")
    cfg_host = os.environ.get("AMY_BAMBU_HOST", "").strip()
    if host and host != cfg_host:
        return Decision("confirm", "probes a host other than the configured printer",
                        f"probe printer at {host}", "medium")
    return _low("check printer")


def _r_bambu_control(a, c):
    host = _s(a, "host")
    cfg_host = os.environ.get("AMY_BAMBU_HOST", "").strip()
    if host and host != cfg_host:
        return Decision("deny", "would send the printer access code to an unconfigured host",
                        f"control printer at {host}", "high")
    if _s(a, "access_code") or _s(a, "serial"):
        return Decision("deny", "printer credentials come from config only", "control printer", "high")
    act = str(a.get("action") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if act in ("light_on", "light_off", "pause"):
        return Decision("allow", "minor printer action", f"printer {act}", "medium")
    return Decision("confirm", "moves or stops physical hardware", f"printer {act or '?'}", "high")


def _r_slicer_open(a, c):
    path = _s(a, "path")
    if not path:
        return _low("open slicer")
    try:
        p = resolve(path, Path.cwd())
    except Exception:
        return Decision("deny", "bad path", "open model", "medium")
    if p.suffix.lower() not in _MODEL_EXTS:
        return Decision("deny", "only 3D model files can be opened in the slicer", f"open {path}", "high")
    if is_sensitive(p):
        return Decision("deny", "path holds secrets", f"open {path}", "high")
    return _low(f"open {p.name} in slicer")


def _r_set_room(a, c):
    room = _s(a, "room")
    return Decision("allow", "switches building lights/fans", f"switch {room or 'room'}", "medium")


def _r_delegate(a, c):
    agent = _s(a, "agent")
    return Decision("allow", "specialist tools are guarded individually",
                    f"ask {agent or 'specialist'}: {_short(_s(a, 'goal'), 80)}", "low")


def _r_reg_read(a, c):
    path = _s(a, "path")
    if path and _REG_READ_DENY_RE.search(path):
        return Decision("deny", "registry area holds credentials", f"read registry {path}", "high")
    return _low(f"read registry {_short(path or _s(a, 'name', 'query'), 80)}")


def _r_reg_write(a, c):
    path = _s(a, "path")
    if not path:
        return Decision("deny", "registry path required", "change registry", "high")
    p = path.replace("/", "\\")
    if _REG_DENY_RE.search(p):
        return Decision("deny", "registry location used for persistence or security bypass",
                        f"change registry {_short(p, 100)}", "high")
    if not re.match(r"^(hkcu|hkey_current_user)\\", p, re.I):
        return Decision("deny", "only HKCU can be changed by Amy", f"change registry {_short(p, 100)}", "high")
    target = f"{p}\\{_s(a, 'name')}" if _s(a, "name") else p
    return Decision("confirm", "changes Windows settings",
                    f"set registry {_short(target, 90)} = {_short(str(a.get('value', '')), 40)}", "high")


def _r_reg_delete(a, c):
    d = _r_reg_write(a, c)
    if d.action == "confirm":
        what = "key" if a.get("delete_key") else "value"
        d.summary = f"delete registry {what} {_short(_s(a, 'path'), 90)}"
    return d


def _r_local_http(a, c):
    method = str(a.get("method") or "GET").upper()
    app = _s(a, "app_id")
    path = _s(a, "path") or "/"
    if method in ("GET", "HEAD"):
        return Decision("allow", "reads a configured local app", f"{method} {app}{path}", "medium")
    return Decision("confirm", "sends a write request to a local app", f"{method} {app}{_short(path, 60)}", "high")


def _r_vision(a, c):
    if a.get("from_camera"):
        return Decision("confirm", "uses the camera", "take a camera picture", "high")
    path = _s(a, "image_path")
    if path:
        verdict, why = check_path(path, c.read_roots)
        if verdict == "deny":
            return Decision("deny", why, f"read image {_short(path, 60)}", "high")
    return Decision("allow", "image from workspace", "recognize image", "medium")


def _r_vision_enroll(a, c):
    d = _r_vision(a, c)
    if d.action == "deny":
        return d
    return Decision("confirm", "stores a person's biometric face data",
                    f"enroll face for {_short(_s(a, 'name'), 40) or 'someone'}", "high")


RULES: Dict[str, Rule] = {
    "tools_catalog": lambda a, c: _low("browse tool packs"),
    "tools_activate": lambda a, c: _low(f"activate tool pack {_s(a, 'pack')}"),
    "os_active_window": lambda a, c: _low("read active window"),
    "os_list_apps": lambda a, c: _low("list installed apps"),
    "reg_query": _r_reg_read,
    "reg_list": _r_reg_read,
    "reg_search": _r_reg_read,
    "reg_analyze_app": lambda a, c: _low(f"analyze app {_short(_s(a, 'name'), 40)}"),
    "reg_set": _r_reg_write,
    "reg_delete": _r_reg_delete,
    "local_app_list": lambda a, c: _low("list local apps"),
    "local_app_status": lambda a, c: _low("check local app"),
    "local_app_open": lambda a, c: _low(f"open local app {_s(a, 'app_id')}"),
    "local_app_http": _r_local_http,
    "vision_status": lambda a, c: _low("check vision"),
    "vision_list_people": lambda a, c: _low("list enrolled people"),
    "vision_recognize": _r_vision,
    "vision_enroll": _r_vision_enroll,
    "updates_status": lambda a, c: _low("check update status"),
    "updates_check": lambda a, c: _low("check for updates"),

    "os_volume": _r_volume,
    "os_mute": lambda a, c: _low("mute/unmute"),
    "os_brightness": lambda a, c: _low("set brightness"),
    "os_toggle": _r_toggle,
    "os_open_app": _r_open_app,
    "browse_url": _r_browse,
    "play_youtube": lambda a, c: _low(f"play {_short(_s(a, 'query'), 60)}"),
    "os_power": _r_power,
    "os_process_list": lambda a, c: _low("list processes"),
    "os_process_kill": _r_kill,
    "run_powershell": _r_shell,
    "run_shell": _r_shell,
    "read_file": _r_files,
    "list_dir": _r_files,
    "web_search": lambda a, c: _low(f"search {_short(_first_str(a, ('query', 'q')), 60)}"),
    "web_fetch": _r_fetch,
    "bambu_status": _r_bambu_status,
    "bambu_control": _r_bambu_control,
    "slicer_find": lambda a, c: _low("find slicers"),
    "slicer_open": _r_slicer_open,
    "smartpanels_status": lambda a, c: _low("check Smart Panel"),
    "smartpanels_login": lambda a, c: _low("log into Smart Panel"),
    "smartpanels_open": lambda a, c: _low("open Smart Panel"),
    "smartpanels_logout": lambda a, c: _low("log out of Smart Panel"),
    "smartpanels_rooms": lambda a, c: _low("list Smart Panel rooms"),
    "smartpanels_set_room": _r_set_room,
    "hive_delegate": _r_delegate,
}


def evaluate(
    tool: str,
    args: Dict[str, Any],
    cfg: GuardConfig,
    *,
    tainted: bool = False,
    source: str = "voice",
    secret_in_args: bool = False,
) -> Decision:
    """Decide what to do with one tool call."""
    if secret_in_args:
        return Decision("deny", "arguments contain a stored secret", f"{tool} call", "high")

    override = cfg.tool_overrides.get(tool)
    if override == "deny":
        return Decision("deny", "disabled in amy.guard.tools", f"{tool} call", "high")

    rule: Optional[Rule] = RULES.get(tool)
    if rule is None:
        d = Decision("confirm", "tool has no safety rule", f"use {tool}", "medium")
    else:
        try:
            d = rule(args, cfg)
        except Exception as e:
            d = Decision("deny", f"safety rule failed: {e}", f"{tool} call", "high")

    if d.action == "deny":
        return d
    if override == "allow" and d.action == "confirm":
        d.action, d.reason = "allow", "allowed in amy.guard.tools"
    elif override == "confirm":
        d.escalate("confirm", "requires approval per amy.guard.tools")

    if cfg.lockdown and tool not in READ_ONLY_TOOLS:
        return Decision("deny", "Amy is in lockdown — only read-only tools run", d.summary, "high")
    if source == "background" and (tool not in READ_ONLY_TOOLS or d.action != "allow"):
        return Decision("deny", "no user turn is active to approve this", d.summary, d.risk)
    if tainted and _RISK_RANK[d.risk] >= 1:
        d.escalate("confirm", "follows untrusted web content in this turn")
    if cfg.strict and _RISK_RANK[d.risk] >= 1:
        d.escalate("confirm", "strict mode")
    return d
