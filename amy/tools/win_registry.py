"""Windows Registry — query, list, set, delete, search/analyze (Win32 only)."""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Tuple

_ROOTS = {
    "HKCU": "HKEY_CURRENT_USER",
    "HKLM": "HKEY_LOCAL_MACHINE",
    "HKCR": "HKEY_CLASSES_ROOT",
    "HKU": "HKEY_USERS",
    "HKEY_CURRENT_USER": "HKEY_CURRENT_USER",
    "HKEY_LOCAL_MACHINE": "HKEY_LOCAL_MACHINE",
    "HKEY_CLASSES_ROOT": "HKEY_CLASSES_ROOT",
    "HKEY_USERS": "HKEY_USERS",
}


def _ok(**payload: Any) -> Dict[str, Any]:
    return {"ok": True, **payload}


def _err(message: str, **payload: Any) -> Dict[str, Any]:
    return {"ok": False, "error": message, **payload}


def _parse_path(path: str) -> Tuple[Any, str]:
    import winreg  # type: ignore

    raw = (path or "").strip().replace("/", "\\")
    if not raw:
        raise ValueError("path required (e.g. HKCU\\Software\\...)")
    parts = raw.split("\\", 1)
    root_name = _ROOTS.get(parts[0].upper(), _ROOTS.get(parts[0]))
    if not root_name:
        raise ValueError(f"Unknown hive {parts[0]!r} — use HKCU/HKLM/HKCR/HKU")
    sub = parts[1] if len(parts) > 1 else ""
    root_map = {
        "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
        "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
        "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
        "HKEY_USERS": winreg.HKEY_USERS,
    }
    return root_map[root_name], sub


def _type_name(t: int) -> str:
    import winreg  # type: ignore

    names = {
        winreg.REG_SZ: "REG_SZ",
        winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
        winreg.REG_DWORD: "REG_DWORD",
        winreg.REG_QWORD: "REG_QWORD",
        winreg.REG_MULTI_SZ: "REG_MULTI_SZ",
        winreg.REG_BINARY: "REG_BINARY",
    }
    return names.get(t, str(t))


def reg_query(path: str = "", name: str = "") -> Dict[str, Any]:
    """Read a registry value (or default) under path. Windows only."""
    if sys.platform != "win32":
        return _err("Registry tools require Windows")
    try:
        import winreg  # type: ignore

        root, sub = _parse_path(path)
        with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as key:
            val_name = "" if name in ("", "(Default)", "@") else name
            value, typ = winreg.QueryValueEx(key, val_name)
            if isinstance(value, bytes):
                shown: Any = value.hex()
            else:
                shown = value
            return _ok(path=path, name=val_name or "(Default)", value=shown, type=_type_name(typ))
    except FileNotFoundError:
        return _err("Key or value not found", path=path, name=name)
    except Exception as e:
        return _err(str(e), path=path)


def reg_list(path: str = "", limit: int = 80) -> Dict[str, Any]:
    """List subkeys and values under a registry path."""
    if sys.platform != "win32":
        return _err("Registry tools require Windows")
    try:
        import winreg  # type: ignore

        root, sub = _parse_path(path)
        lim = max(1, min(200, int(limit or 80)))
        with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as key:
            subkeys: List[str] = []
            values: List[Dict[str, Any]] = []
            i = 0
            while len(subkeys) < lim:
                try:
                    subkeys.append(winreg.EnumKey(key, i))
                    i += 1
                except OSError:
                    break
            i = 0
            while len(values) < lim:
                try:
                    n, v, t = winreg.EnumValue(key, i)
                    if isinstance(v, bytes):
                        v = v.hex()
                    values.append({"name": n or "(Default)", "value": v, "type": _type_name(t)})
                    i += 1
                except OSError:
                    break
            return _ok(path=path, subkeys=subkeys, values=values, subkey_count=len(subkeys), value_count=len(values))
    except FileNotFoundError:
        return _err("Key not found", path=path)
    except Exception as e:
        return _err(str(e), path=path)


def reg_set(
    path: str = "",
    name: str = "",
    value: str = "",
    value_type: str = "REG_SZ",
) -> Dict[str, Any]:
    """Create/set a registry value. Prefer HKCU; HKLM may need elevation."""
    if sys.platform != "win32":
        return _err("Registry tools require Windows")
    try:
        import winreg  # type: ignore

        root, sub = _parse_path(path)
        tname = (value_type or "REG_SZ").upper()
        typ_map = {
            "REG_SZ": winreg.REG_SZ,
            "REG_EXPAND_SZ": winreg.REG_EXPAND_SZ,
            "REG_DWORD": winreg.REG_DWORD,
            "REG_QWORD": winreg.REG_QWORD,
            "REG_MULTI_SZ": winreg.REG_MULTI_SZ,
        }
        typ = typ_map.get(tname, winreg.REG_SZ)
        raw: Any = value
        if typ == winreg.REG_DWORD:
            raw = int(str(value), 0)
        elif typ == winreg.REG_QWORD:
            raw = int(str(value), 0)
        elif typ == winreg.REG_MULTI_SZ:
            raw = [p for p in str(value).split("\n") if p != ""]
        with winreg.CreateKeyEx(root, sub, 0, winreg.KEY_SET_VALUE) as key:
            val_name = "" if name in ("", "(Default)", "@") else name
            winreg.SetValueEx(key, val_name, 0, typ, raw)
        return _ok(path=path, name=val_name or "(Default)", value=value, type=tname)
    except PermissionError:
        return _err("Access denied — try HKCU or run elevated for HKLM", path=path)
    except Exception as e:
        return _err(str(e), path=path)


def reg_delete(path: str = "", name: str = "", delete_key: bool = False) -> Dict[str, Any]:
    """Delete a registry value, or the key itself when delete_key=true."""
    if sys.platform != "win32":
        return _err("Registry tools require Windows")
    try:
        import winreg  # type: ignore

        root, sub = _parse_path(path)
        if delete_key:
            # Delete empty-ish key — use DeleteKey on parent
            if "\\" not in sub:
                return _err("Refusing to delete a hive root")
            parent, _, leaf = sub.rpartition("\\")
            with winreg.OpenKey(root, parent, 0, winreg.KEY_WRITE) as key:
                winreg.DeleteKey(key, leaf)
            return _ok(deleted_key=path)
        with winreg.OpenKey(root, sub, 0, winreg.KEY_SET_VALUE) as key:
            val_name = "" if name in ("", "(Default)", "@") else name
            winreg.DeleteValue(key, val_name)
        return _ok(deleted_value=val_name or "(Default)", path=path)
    except FileNotFoundError:
        return _err("Key or value not found", path=path)
    except PermissionError:
        return _err("Access denied", path=path)
    except Exception as e:
        return _err(str(e), path=path)


def reg_search(
    path: str = "HKCU\\Software",
    query: str = "",
    max_hits: int = 40,
) -> Dict[str, Any]:
    """Search key/value names (and string values) under a registry path."""
    if sys.platform != "win32":
        return _err("Registry tools require Windows")
    needle = (query or "").strip().lower()
    if not needle:
        return _err("query required")
    if not (path or "").strip():
        return _err("path required")
    try:
        import winreg  # type: ignore

        root, sub = _parse_path(path)
        hits: List[Dict[str, Any]] = []
        lim = max(1, min(100, int(max_hits or 40)))

        def walk(hkey: Any, cur: str, depth: int = 0) -> None:
            if len(hits) >= lim or depth > 8:
                return
            # values
            i = 0
            while len(hits) < lim:
                try:
                    n, v, t = winreg.EnumValue(hkey, i)
                    i += 1
                    blob = f"{n} {v}".lower()
                    if needle in blob:
                        hits.append(
                            {
                                "path": cur,
                                "name": n or "(Default)",
                                "value": v if not isinstance(v, bytes) else v.hex(),
                                "type": _type_name(t),
                            }
                        )
                except OSError:
                    break
            # subkeys
            names = []
            i = 0
            while True:
                try:
                    names.append(winreg.EnumKey(hkey, i))
                    i += 1
                except OSError:
                    break
            for name in names:
                if len(hits) >= lim:
                    break
                child_path = f"{cur}\\{name}" if cur else name
                if needle in name.lower():
                    hits.append({"path": child_path, "name": "(key)", "value": "", "type": "KEY"})
                try:
                    with winreg.OpenKey(hkey, name, 0, winreg.KEY_READ) as child:
                        walk(child, child_path, depth + 1)
                except OSError:
                    continue

        with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as key:
            walk(key, path)
        return _ok(path=path, query=query, hits=hits, count=len(hits))
    except Exception as e:
        return _err(str(e), path=path)


def reg_analyze_app(name: str = "") -> Dict[str, Any]:
    """Analyze where an app is registered (App Paths, Uninstall, Classes)."""
    if sys.platform != "win32":
        return _err("Registry tools require Windows")
    app = (name or "").strip()
    if not app:
        return _err("name required (e.g. chrome.exe or Notion)")
    q = app.lower().replace(".exe", "")
    paths = [
        r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
        r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
        r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    ]
    findings: List[Dict[str, Any]] = []
    for p in paths:
        res = reg_search(path=p, query=q, max_hits=15)
        if res.get("ok"):
            for h in res.get("hits") or []:
                findings.append({"scope": p, **h})
    # Also try direct App Paths\<name>.exe
    for hive in ("HKLM", "HKCU"):
        direct = f"{hive}\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{q}.exe"
        got = reg_query(direct, name="")
        if got.get("ok"):
            findings.append({"scope": "App Paths", "path": direct, **{k: got[k] for k in ("name", "value", "type") if k in got}})
        got2 = reg_list(direct, limit=20)
        if got2.get("ok"):
            findings.append({"scope": "App Paths values", "path": direct, "values": got2.get("values")})
    return _ok(app=app, findings=findings, count=len(findings))


def register(registry: Any) -> List[str]:
    specs = [
        (reg_query, "Read a Windows registry value. path=HKCU\\... name=optional."),
        (reg_list, "List subkeys/values under a Windows registry path."),
        (reg_set, "Set/create a registry value (HKCU preferred; HKLM may need admin)."),
        (reg_delete, "Delete a registry value or key (delete_key=true)."),
        (reg_search, "Search registry names/values under a path."),
        (reg_analyze_app, "Analyze where an app is registered (App Paths / Uninstall)."),
    ]
    out: List[str] = []
    for fn, desc in specs:
        try:
            registry.register(
                fn, name=fn.__name__, description=desc, module="amy_registry", overwrite=True
            )
            out.append(fn.__name__)
        except Exception:
            continue
    return out
