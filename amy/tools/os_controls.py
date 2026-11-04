"""Pure OS controls for Amy — volume, mute, brightness, toggles, apps, browse.

Windows-first. Absolute volume uses Core Audio (no nircmd). Brightness uses
WMI via Invoke-CimMethod / Get-WmiObject with a clear fallback.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import webbrowser
from typing import Any, Dict, List, Optional


def _ok(**payload: Any) -> Dict[str, Any]:
    return {"ok": True, **payload}


def _err(message: str, **payload: Any) -> Dict[str, Any]:
    return {"ok": False, "error": message, **payload}


def _ps(script: str, *, timeout: float = 20.0) -> Dict[str, Any]:
    if sys.platform != "win32":
        return _err("OS controls currently target Windows")
    # Wrap so a terminating error always yields a non-zero exit + message
    wrapped = (
        "$ErrorActionPreference = 'Stop'\n"
        "try {\n"
        f"{script}\n"
        "} catch {\n"
        "  [Console]::Error.WriteLine($_.Exception.Message)\n"
        "  exit 1\n"
        "}\n"
    )
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                wrapped,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as e:
        return _err(str(e))
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return _err(stderr or stdout or f"exit {proc.returncode}", code=proc.returncode)
    # Scripts that print error=... but exit 0
    if stdout.lower().startswith("error="):
        return _err(stdout[6:].strip() or stdout)
    return _ok(output=stdout)


def os_volume(level: Optional[int] = None, delta: Optional[int] = None) -> Dict[str, Any]:
    """Set or nudge system volume (0–100). Prefer level, or delta (+/-)."""
    if level is None and delta is None:
        return _err("Pass level (0-100) or delta (+/- percent)")
    try:
        from amy.tools.win_audio import available, volume_control

        if available():
            return volume_control(level=level, delta=delta)
    except Exception as e:
        # Fall through to key simulation
        fallback_err = str(e)
    else:
        fallback_err = "pycaw unavailable"

    # Last-resort: hardware media keys (~2% per tap)
    d = int(delta) if delta is not None else None
    if level is not None and d is None:
        # Approximate absolute: drain then raise
        lvl = max(0, min(100, int(level)))
        script = f"""
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public static class AmyKeys {{
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, uint dwExtraInfo);
}}
"@
1..50 | ForEach-Object {{ [AmyKeys]::keybd_event(0xAE, 0, 0, 0); [AmyKeys]::keybd_event(0xAE, 0, 2, 0); Start-Sleep -Milliseconds 12 }}
$taps = [Math]::Max(0, [Math]::Min(50, [int][Math]::Round({lvl} / 2.0)))
1..$taps | ForEach-Object {{ [AmyKeys]::keybd_event(0xAF, 0, 0, 0); [AmyKeys]::keybd_event(0xAF, 0, 2, 0); Start-Sleep -Milliseconds 12 }}
"volume~={lvl}; via=keys; note={fallback_err}"
"""
        return _ps(script, timeout=30)
    d = int(d or 0)
    if d == 0:
        return _err("delta must be non-zero")
    taps = max(1, min(25, abs(d) // 2 or 1))
    vk = 0xAF if d > 0 else 0xAE
    script = f"""
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public static class AmyKeys2 {{
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, uint dwExtraInfo);
}}
"@
1..{taps} | ForEach-Object {{ [AmyKeys2]::keybd_event({vk}, 0, 0, 0); [AmyKeys2]::keybd_event({vk}, 0, 2, 0); Start-Sleep -Milliseconds 15 }}
"delta={d}; taps={taps}; via=keys"
"""
    return _ps(script)


def os_mute(muted: Optional[bool] = None) -> Dict[str, Any]:
    """Toggle or set system mute. muted=true/false, or omit to toggle."""
    try:
        from amy.tools.win_audio import available, mute_control

        if available():
            return mute_control(muted)
    except Exception:
        pass
    # Media-key mute toggle (cannot force on/off without Core Audio)
    script = """
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public static class AmyMuteKey {
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, uint dwExtraInfo);
}
"@
[AmyMuteKey]::keybd_event(0xAD, 0, 0, 0)
Start-Sleep -Milliseconds 40
[AmyMuteKey]::keybd_event(0xAD, 0, 2, 0)
"muted=toggled; via=keys"
"""
    return _ps(script)


def os_brightness(level: Optional[int] = None, delta: Optional[int] = None) -> Dict[str, Any]:
    """Set display brightness 0–100, or nudge with delta (built-in panel via WMI)."""
    if level is None and delta is None:
        return _err("Pass level (0-100) or delta")

    # Shared setter — Invoke-CimMethod is the supported path; WmiObject is fallback.
    setter = r"""
function Set-AmyBrightness([int]$Level) {
  $Level = [Math]::Max(0, [Math]::Min(100, $Level))
  $errs = @()
  try {
    $r = Invoke-CimMethod -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods `
      -MethodName WmiSetBrightness -Arguments @{ Timeout = [uint32]1; Brightness = [uint32]$Level } `
      -ErrorAction Stop
    return "brightness=$Level"
  } catch { $errs += $_.Exception.Message }
  try {
    $m = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods -ErrorAction Stop
    foreach ($inst in @($m)) {
      $inst.WmiSetBrightness(1, $Level) | Out-Null
    }
    return "brightness=$Level"
  } catch { $errs += $_.Exception.Message }
  # Last resort: brightness keys (laptops). VK 0xE0/0xE1 not standard — open Display settings.
  Start-Process "ms-settings:display"
  throw ("Brightness API unavailable (external monitor?). Opened Display settings. " + ($errs -join ' | '))
}
function Get-AmyBrightness {
  try {
    $b = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop |
      Select-Object -First 1 -ExpandProperty CurrentBrightness
    return [int]$b
  } catch {
    try {
      return [int](Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness -ErrorAction Stop |
        Select-Object -First 1 -ExpandProperty CurrentBrightness)
    } catch { return -1 }
  }
}
"""
    if level is not None:
        lvl = max(0, min(100, int(level)))
        script = setter + f"Set-AmyBrightness {lvl}\n"
        return _ps(script)

    d = int(delta or 0)
    script = (
        setter
        + f"""
$cur = Get-AmyBrightness
if ($cur -lt 0) {{
  Start-Process "ms-settings:display"
  throw "Cannot read current brightness (often external monitors). Opened Display settings."
}}
$next = [Math]::Max(0, [Math]::Min(100, $cur + ({d})))
Set-AmyBrightness $next
"""
    )
    return _ps(script)


def os_toggle(feature: str, enabled: Optional[bool] = None) -> Dict[str, Any]:
    """Toggle OS features: wifi, bluetooth, dark_mode, night_light, airplane."""
    feat = (feature or "").strip().lower().replace("-", "_").replace(" ", "_")
    if feat in ("wifi", "wi_fi"):
        # Prefer netsh (often works without full admin Confirm prompts)
        if enabled is None:
            script = """
$a = Get-NetAdapter | Where-Object { $_.Status -ne 'Not Present' -and ($_.Name -match 'Wi-?Fi|Wireless' -or $_.InterfaceDescription -match 'Wireless|Wi-?Fi|802\\.11') } | Select-Object -First 1
if (-not $a) { throw "No Wi-Fi adapter found" }
if ($a.Status -eq "Up") {
  Disable-NetAdapter -Name $a.Name -Confirm:$false
  "wifi=off; adapter=$($a.Name)"
} else {
  Enable-NetAdapter -Name $a.Name -Confirm:$false
  "wifi=on; adapter=$($a.Name)"
}
"""
        elif enabled:
            script = """
$a = Get-NetAdapter | Where-Object { $_.Name -match 'Wi-?Fi|Wireless' -or $_.InterfaceDescription -match 'Wireless|Wi-?Fi|802\\.11' } | Select-Object -First 1
if (-not $a) { throw "No Wi-Fi adapter found" }
Enable-NetAdapter -Name $a.Name -Confirm:$false
"wifi=on; adapter=$($a.Name)"
"""
        else:
            script = """
$a = Get-NetAdapter | Where-Object { $_.Name -match 'Wi-?Fi|Wireless' -or $_.InterfaceDescription -match 'Wireless|Wi-?Fi|802\\.11' } | Select-Object -First 1
if (-not $a) { throw "No Wi-Fi adapter found" }
Disable-NetAdapter -Name $a.Name -Confirm:$false
"wifi=off; adapter=$($a.Name)"
"""
        out = _ps(script)
        if not out.get("ok"):
            webbrowser.open("ms-settings:network-wifi")
            out["opened"] = "ms-settings:network-wifi"
            out["note"] = "Wi-Fi toggle may need admin — opened Settings"
        return out

    if feat in ("bluetooth", "bt"):
        webbrowser.open("ms-settings:bluetooth")
        return _ok(
            feature="bluetooth",
            opened="ms-settings:bluetooth",
            note="Bluetooth radio toggle needs Settings / admin on most PCs",
        )

    if feat in ("dark_mode", "dark", "theme"):
        if enabled is None:
            script = """
$path = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize'
$cur = (Get-ItemProperty -Path $path -Name AppsUseLightTheme).AppsUseLightTheme
$next = if ($cur -eq 1) { 0 } else { 1 }
Set-ItemProperty -Path $path -Name AppsUseLightTheme -Value $next
Set-ItemProperty -Path $path -Name SystemUsesLightTheme -Value $next
if ($next -eq 0) { "dark_mode=on" } else { "dark_mode=off" }
"""
        else:
            next_val = 0 if enabled else 1
            script = f"""
$path = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize'
Set-ItemProperty -Path $path -Name AppsUseLightTheme -Value {next_val}
Set-ItemProperty -Path $path -Name SystemUsesLightTheme -Value {next_val}
if ({next_val} -eq 0) {{ "dark_mode=on" }} else {{ "dark_mode=off" }}
"""
        return _ps(script)

    if feat in ("night_light", "nightlight", "blue_light"):
        webbrowser.open("ms-settings:nightlight")
        return _ok(feature="night_light", opened="ms-settings:nightlight")

    if feat in ("airplane", "airplane_mode"):
        webbrowser.open("ms-settings:network-airplanemode")
        return _ok(feature="airplane", opened="ms-settings:network-airplanemode")

    return _err(
        f"Unknown feature {feature!r}",
        supported=["wifi", "bluetooth", "dark_mode", "night_light", "airplane"],
    )


def _resolve_app_windows(target: str) -> Dict[str, Any]:
    """Resolve an app via aliases, App Paths registry, Start Menu, Get-StartApps."""
    aliases = {
        "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
        "notepad": "notepad.exe",
        "explorer": "explorer.exe",
        "terminal": "wt.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "settings": "ms-settings:",
        "calculator": "calc.exe",
        "display": "ms-settings:display",
        "sound": "ms-settings:sound",
    }
    key = target.lower().strip()
    if key in aliases:
        return _ok(resolved=aliases[key], method="alias")
    if target.lower().startswith("ms-") or "://" in target:
        return _ok(resolved=target, method="uri")
    if os.path.isfile(target):
        return _ok(resolved=target, method="path")

    # App Paths registry (HKCU then HKLM)
    try:
        import winreg  # type: ignore

        exe = key if key.endswith(".exe") else f"{key}.exe"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(
                    hive,
                    rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}",
                ) as k:
                    val, _ = winreg.QueryValueEx(k, "")
                    if val and os.path.isfile(str(val)):
                        return _ok(resolved=str(val), method="app_paths")
            except OSError:
                continue
    except Exception:
        pass

    # Get-StartApps (AppX + classic)
    out = _ps(
        f"$q='{key.replace(chr(39), '')}'; "
        "Get-StartApps | Where-Object { $_.Name -like \"*$q*\" -or $_.AppID -like \"*$q*\" } "
        "| Select-Object -First 5 Name, AppID | ConvertTo-Json -Compress",
        timeout=15.0,
    )
    if out.get("ok") and out.get("output"):
        try:
            import json

            data = json.loads(out["output"])
            if isinstance(data, dict):
                data = [data]
            if isinstance(data, list) and data:
                app_id = str(data[0].get("AppID") or "")
                name = str(data[0].get("Name") or "")
                if app_id:
                    return _ok(
                        resolved=app_id,
                        display_name=name,
                        method="start_apps",
                        matches=data[:5],
                    )
        except Exception:
            pass

    # where.exe / PATH
    exe_guess = key if key.endswith(".exe") else f"{key}.exe"
    which = shutil.which(target) or shutil.which(exe_guess)
    if which:
        return _ok(resolved=which, method="path_env")

    return _err(f"Could not resolve app {target!r}")


def os_list_apps(query: str = "", limit: int = 40) -> Dict[str, Any]:
    """List installed / Start Menu apps (Windows Get-StartApps + App Paths sample)."""
    lim = max(1, min(120, int(limit or 40)))
    q = (query or "").strip().lower()
    if sys.platform != "win32":
        # Best-effort: PATH executables are not a full catalog on Unix
        return _ok(platform=sys.platform, apps=[], note="Full catalog is Windows-first")

    out = _ps(
        "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress",
        timeout=20.0,
    )
    apps: List[Dict[str, Any]] = []
    if out.get("ok") and out.get("output"):
        try:
            import json

            data = json.loads(out["output"])
            if isinstance(data, dict):
                data = [data]
            for row in data or []:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("Name") or "")
                app_id = str(row.get("AppID") or "")
                if q and q not in name.lower() and q not in app_id.lower():
                    continue
                apps.append({"name": name, "id": app_id, "source": "start_apps"})
                if len(apps) >= lim:
                    break
        except Exception as e:
            return _err(str(e))
    return _ok(count=len(apps), query=q or None, apps=apps)


def os_open_app(name: str = "", path: str = "") -> Dict[str, Any]:
    """Open any app by name, Start Menu title, AppID, URI, or full path (cross-platform)."""
    target = (path or "").strip() or (name or "").strip()
    if not target:
        return _err("Pass name or path")

    key = target.lower()
    if key in ("settings", "display", "sound") or target.startswith("ms-"):
        uri = {
            "settings": "ms-settings:",
            "display": "ms-settings:display",
            "sound": "ms-settings:sound",
        }.get(key, target)
        webbrowser.open(uri)
        return _ok(opened=uri, method="uri")

    if sys.platform == "win32":
        resolved = _resolve_app_windows(target)
        if not resolved.get("ok"):
            return resolved
        exe = str(resolved.get("resolved") or "")
        method = str(resolved.get("method") or "")
        try:
            # AppX / shell AppIDs: shell:AppsFolder\... or PackageFamily!App
            if method == "start_apps" or ("!" in exe and not os.path.isfile(exe)):
                proc = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        f"try {{ Start-Process $('{exe.replace(chr(39), '')}') }} "
                        f"catch {{ Start-Process explorer.exe -ArgumentList 'shell:AppsFolder\\{exe.replace(chr(39), '')}' }}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                if proc.returncode == 0:
                    return _ok(opened=exe, method=method, display_name=resolved.get("display_name"))
            esc = exe.replace("'", "''")
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    f"Start-Process -FilePath '{esc}'",
                ],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
            if proc.returncode == 0:
                return _ok(opened=exe, method=method)
            os.startfile(exe)  # type: ignore[attr-defined]
            return _ok(opened=exe, method=method)
        except Exception as e:
            try:
                os.startfile(exe)  # type: ignore[attr-defined]
                return _ok(opened=exe, method=method)
            except Exception as e2:
                return _err(f"{e}; {e2}")

    # macOS / Linux
    if sys.platform == "darwin":
        try:
            subprocess.Popen(["open", "-a", target] if not os.path.isfile(target) else ["open", target])
            return _ok(opened=target, method="open")
        except Exception as e:
            return _err(str(e))
    # Linux: desktop files / PATH
    which = shutil.which(target)
    try:
        if which:
            subprocess.Popen([which])
            return _ok(opened=which, method="path")
        subprocess.Popen(["xdg-open", target])
        return _ok(opened=target, method="xdg-open")
    except Exception as e:
        return _err(str(e))


def browse_url(url: str = "", query: str = "") -> Dict[str, Any]:
    """Open a URL in the default browser, or search the web with query."""
    u = (url or "").strip()
    q = (query or "").strip()
    if not u and not q:
        return _err("Pass url or query")
    if not u and q:
        from urllib.parse import quote_plus

        u = f"https://duckduckgo.com/?q={quote_plus(q)}"
    if not u.lower().startswith(("http://", "https://", "ms-settings:")):
        u = "https://" + u
    try:
        webbrowser.open(u)
        return _ok(opened=u)
    except Exception as e:
        return _err(str(e), url=u)


def play_youtube(query: str = "", music: bool = True) -> Dict[str, Any]:
    """Open YouTube (or YouTube Music) search for a song / video query."""
    q = (query or "").strip()
    if not q:
        return _err("Pass a song or video query")
    from urllib.parse import quote_plus

    if music:
        u = f"https://music.youtube.com/search?q={quote_plus(q)}"
    else:
        u = f"https://www.youtube.com/results?search_query={quote_plus(q)}"
    try:
        webbrowser.open(u)
        return _ok(opened=u, query=q, music=bool(music))
    except Exception as e:
        return _err(str(e), url=u)


_PROTECTED_PROCESSES = frozenset(
    {
        "system",
        "idle",
        "csrss",
        "csrss.exe",
        "wininit",
        "wininit.exe",
        "winlogon",
        "winlogon.exe",
        "services",
        "services.exe",
        "lsass",
        "lsass.exe",
        "smss",
        "smss.exe",
        "svchost",
        "svchost.exe",
        "explorer",
        "explorer.exe",
        "dwm",
        "lsaiso",
        "msmpeng",
        "nissrv",
        "securityhealthservice",
        "mpdefendercoreservice",
        "python",
        "pythonw",
    }
)


def os_process_list(name: str = "", limit: int = 20) -> Dict[str, Any]:
    """List running processes, optionally filtered by name substring."""
    if sys.platform != "win32":
        return _err("os_process_list currently targets Windows")
    needle = (name or "").strip().lower().replace(".exe", "")
    lim = max(1, min(80, int(limit or 20)))
    script = (
        "Get-Process | Select-Object Id, ProcessName, CPU | "
        "Sort-Object CPU -Descending | ConvertTo-Json -Compress"
    )
    out = _ps(script, timeout=25.0)
    if not out.get("ok"):
        return out
    raw = out.get("output") or "[]"
    try:
        import json

        data = json.loads(raw) if raw else []
    except Exception:
        return _err("Could not parse process list", raw=str(raw)[:200])
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        data = []
    rows: List[Dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        pname = str(row.get("ProcessName") or "")
        if needle and needle not in pname.lower():
            continue
        rows.append(
            {
                "pid": row.get("Id"),
                "name": pname,
                "cpu": row.get("CPU"),
            }
        )
        if len(rows) >= lim:
            break
    return _ok(count=len(rows), processes=rows, filter=needle or None)


def os_process_kill(name: str = "", pid: Optional[int] = None) -> Dict[str, Any]:
    """Kill a Windows process by name (e.g. boa / boa.exe) or PID. Acts immediately."""
    if sys.platform != "win32":
        return _err("os_process_kill currently targets Windows")
    if pid is not None:
        try:
            pid_i = int(pid)
        except Exception:
            return _err("pid must be an integer")
        if pid_i <= 0:
            return _err("invalid pid")
        out = _ps(f"Stop-Process -Id {pid_i} -Force; 'killed_pid={pid_i}'", timeout=20.0)
        if out.get("ok"):
            return _ok(killed_pid=pid_i, method="pid")
        return out

    raw_name = (name or "").strip()
    if not raw_name:
        return _err("Provide name= (process name) or pid=")
    # Interpolated into PowerShell below — anything outside this set could break out of the quotes.
    if not re.fullmatch(r"[A-Za-z0-9._ \-]{1,64}", raw_name):
        return _err(f"Invalid process name {raw_name!r}")
    base = raw_name.lower().replace(".exe", "").strip()
    if not base or base in _PROTECTED_PROCESSES or f"{base}.exe" in _PROTECTED_PROCESSES:
        return _err(f"Refusing to kill protected process {raw_name!r}")
    # Prefer exact image name match via taskkill
    image = raw_name if raw_name.lower().endswith(".exe") else f"{base}.exe"
    out = _ps(
        f"$n='{image}'; "
        "if (-not (Get-Process -Name ($n -replace '\\.exe$','') -ErrorAction SilentlyContinue)) "
        "{ throw \"process not found: $n\" }; "
        "Stop-Process -Name ($n -replace '\\.exe$','') -Force; "
        "'killed=' + $n",
        timeout=25.0,
    )
    if out.get("ok"):
        return _ok(killed=image, method="name")
    return out


def os_power(
    action: str = "shutdown",
    delay_seconds: Optional[int] = 60,
) -> Dict[str, Any]:
    """Windows power: shutdown / restart / cancel / sleep / lock.

    Shutdown and restart use a delay (default 60s) so you can cancel with
    action='cancel'. Explicit voice phrases should call this — not casual chat.
    """
    if sys.platform != "win32":
        return _err("os_power currently targets Windows")
    act = (action or "").strip().lower().replace("-", "_").replace(" ", "_")
    delay = 60 if delay_seconds is None else max(0, min(600, int(delay_seconds)))

    if act in ("cancel", "abort", "cancel_shutdown", "abort_shutdown"):
        out = _ps("shutdown /a; 'cancelled'")
        if out.get("ok"):
            return _ok(action="cancel", output=out.get("output") or "cancelled")
        # No pending shutdown is fine
        err = str(out.get("error") or "")
        if "1116" in err or "not in the process" in err.lower() or "unable" in err.lower():
            return _ok(action="cancel", note="No shutdown was pending")
        return out

    if act in ("lock", "lock_workstation"):
        try:
            subprocess.Popen(
                ["rundll32.exe", "user32.dll,LockWorkStation"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return _ok(action="lock")
        except Exception as e:
            return _err(str(e))

    if act in ("sleep", "suspend"):
        try:
            subprocess.Popen(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return _ok(action="sleep")
        except Exception as e:
            return _err(str(e))

    if act in ("shutdown", "power_off", "poweroff", "halt"):
        # /f force apps; /t delay; /c comment
        cmd = f'shutdown /s /f /t {delay} /c "Amy scheduled shutdown"'
        out = _ps(f"{cmd}; 'shutdown_in={delay}'")
        if out.get("ok"):
            return _ok(action="shutdown", delay_seconds=delay)
        return out

    if act in ("restart", "reboot"):
        cmd = f'shutdown /r /f /t {delay} /c "Amy scheduled restart"'
        out = _ps(f"{cmd}; 'restart_in={delay}'")
        if out.get("ok"):
            return _ok(action="restart", delay_seconds=delay)
        return out

    return _err(
        f"Unknown action {action!r}",
        supported=["shutdown", "restart", "cancel", "sleep", "lock"],
    )


def os_active_window() -> Dict[str, Any]:
    """Return the focused desktop window title + process (environment glance)."""
    try:
        from amy.host.env_context import sample_env

        snap = sample_env()
        return _ok(
            process=snap.process_name,
            title=snap.window_title,
            local_time=snap.local_time,
            weekday=snap.weekday,
            home=snap.home_label,
            summary=snap.summary,
        )
    except Exception as e:
        return _err(str(e))


def register(registry: Any) -> List[str]:
    specs = [
        (os_volume, "Set or nudge Windows volume (level 0-100 or delta). Uses Core Audio."),
        (os_mute, "Mute, unmute, or toggle system audio via Core Audio."),
        (
            os_brightness,
            "Set or nudge display brightness 0-100 (laptop WMI). Opens Display settings if unsupported.",
        ),
        (
            os_toggle,
            "Toggle wifi / bluetooth / dark_mode / night_light / airplane.",
        ),
        (
            os_open_app,
            "Open any app by Start Menu name, AppID, alias, URI, or full path.",
        ),
        (
            os_list_apps,
            "List/search installed Start Menu apps (query=, limit=). Use before os_open_app.",
        ),
        (browse_url, "Open a URL or web search query in the default browser."),
        (
            play_youtube,
            "Open YouTube Music (or YouTube) search to play a song/video. query=artist or track.",
        ),
        (
            os_power,
            "Windows power: shutdown/restart (delayed), cancel, sleep, or lock. Prefer delay_seconds=60.",
        ),
        (
            os_process_list,
            "List running processes (optional name= filter). Use before kill if unsure.",
        ),
        (
            os_process_kill,
            "Kill a process NOW by name= (e.g. boa) or pid=. Do not web_search — call this.",
        ),
        (
            os_active_window,
            "Glance at the focused window (title + process + local time). Use for 'what's on screen' / 'this'.",
        ),
    ]
    out: List[str] = []
    for fn, desc in specs:
        name = fn.__name__
        try:
            registry.register(
                fn, name=name, description=desc, module="amy_os", overwrite=True
            )
            out.append(name)
        except Exception:
            continue
    return out
