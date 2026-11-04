"""Static risk classification for agent-issued PowerShell / cmd commands.

Verdicts: ``allow`` (read-only, runs without asking), ``confirm`` (needs a
human yes), ``deny`` (never runs, even with approval).
"""

from __future__ import annotations

import re
from typing import List, Tuple

MAX_COMMAND_CHARS = 2000

_DENY: List[Tuple[str, str]] = [
    # Download-and-execute / obfuscation
    (r"\b(invoke-expression|iex)\b", "dynamic code execution (Invoke-Expression)"),
    (r"\b(powershell|pwsh)(\.exe)?\b.*\s-(e|ec|en|enc|enco|encodedcommand)\b", "encoded command"),
    (r"frombase64string|\[convert\]::|system\.text\.encoding", "base64/encoding obfuscation"),
    (r"\[char\]\s*\d|-bxor\b", "character-code obfuscation"),
    (r"%[a-z_]+:~", "cmd variable-substring obfuscation"),
    (r"downloadstring|downloadfile|downloaddata|net\.webclient|start-bitstransfer|bitsadmin", "download-and-run"),
    (r"\bcertutil\b.*-(urlcache|decode|encode)", "certutil download/decode"),
    (r"\badd-type\b", "compiling arbitrary code (Add-Type)"),
    (r"\b(mshta|regsvr32|rundll32|cscript|wscript|installutil|msbuild)\b", "living-off-the-land binary"),
    # Destructive file / disk operations
    (r"\b(remove-item|ri|rm|del|erase|rmdir|rd)\b[^;|&]*(\s-r\b|-recurse|-rf\b|\s/s\b)", "recursive delete"),
    (r"\b(remove-item|ri|rm|del|erase)\b[^;|&]*\*", "wildcard delete"),
    (r"(^|[\s;|&])format(\.com)?\s+[a-z]:", "disk format"),
    (r"\b(format-volume|clear-disk|initialize-disk|remove-partition|set-partition|diskpart)\b", "disk/partition change"),
    (r"\bcipher(\.exe)?\s+/w|\bvssadmin\b|\bwbadmin\b|shadowcopy|\bbcdedit\b|\bbootrec\b", "backup/boot tampering"),
    (r"\b(clear-eventlog|remove-eventlog)\b|\bwevtutil(\.exe)?\s+(cl|clear-log)\b", "log wiping"),
    # Security controls
    (r"\b(set-mppreference|add-mppreference)\b|disablerealtimemonitoring", "Defender tampering"),
    (r"\bnetsh\b.*firewall.*\b(off|disable)\b|set-netfirewallprofile.*\$?false", "firewall disable"),
    (r"\bsc(\.exe)?\s+(stop|config|delete)\s+(windefend|wscsvc|mpssvc|securityhealthservice)", "security service tampering"),
    (r"\bset-executionpolicy\b", "execution policy change"),
    (r"\btakeown\b|\bicacls\b.*/grant", "permission takeover"),
    # Accounts / persistence / elevation / lateral movement
    (r"\bnet(\.exe)?\s+(user|localgroup|share)\b", "account/share change"),
    (r"\b(new-localuser|set-localuser|remove-localuser|add-localgroupmember)\b", "account change"),
    (r"\bschtasks(\.exe)?\s*/create|\b(register-scheduledtask|new-scheduledtask)\b", "scheduled-task persistence"),
    (r"\bnew-service\b|\bsc(\.exe)?\s+create\b", "service persistence"),
    (r"currentversion\\+run", "autorun persistence"),
    (r"\breg(\.exe)?\s+(delete|import|load|restore|save|unload)\b", "registry hive change"),
    (r"-verb\s+runas|\brunas(\.exe)?\s", "privilege elevation"),
    (r"\b(invoke-command|enter-pssession|new-pssession|psexec|invoke-wmimethod)\b", "remote execution"),
    (r"\bwmic\b.*\b(process\s+call\s+create|shadowcopy)\b", "remote execution"),
    # Power — must go through os_power (delayed + cancellable)
    (r"\b(shutdown|stop-computer|restart-computer|logoff)\b", "power action (use os_power)"),
    # Credentials and secrets
    (r"mimikatz|sekurlsa|\blsass\b|procdump|comsvcs|ntds\.dit|\\sam\b", "credential dumping"),
    (r"\b(cmdkey|vaultcmd|get-credential|convertfrom-securestring)\b|secretmanagement", "credential store access"),
    (r"\.ssh[\\/]|id_rsa|id_ed25519|\.kdbx\b|wallet\.dat|\.git-credentials|\.netrc\b", "secret file access"),
    (r"\.amy[\\/](secrets|state)|(^|[\\/\s'\"])\.env\b", "Amy secret file access"),
    (r"login data|\\cookies\b|user data\\default|\\protect\\|\\credentials\\", "browser/OS credential store"),
]

_DENY_RE = [(re.compile(p, re.I), why) for p, why in _DENY]

# Commands that only read state. A segment runs unattended only if its first
# token is here and (when listed) its arguments pass the validator.
_SAFE_COMMANDS = {
    "test-connection", "test-netconnection", "resolve-dnsname",
    "select-object", "where-object", "sort-object", "measure-object",
    "format-table", "format-list", "format-wide", "convertto-json", "convertto-csv",
    "out-string", "write-output", "echo",
    "ping", "hostname", "whoami", "systeminfo", "tasklist", "netstat",
    "nslookup", "tracert", "getmac", "nvidia-smi",
    "dir", "ls", "gci", "gps", "ps", "pwd", "uptime",
}
_SAFE_ARGS = {
    "ipconfig": lambda a: a in ("", "/all"),
    "arp": lambda a: a in ("-a", "/a", ""),
}
_UNSAFE_GET = {
    "get-content", "get-credential", "get-clipboard", "get-history",
    "get-secret", "get-secretinfo",
}


def _normalize(cmd: str) -> str:
    # Strip PowerShell backtick and cmd caret escapes used to split keywords.
    s = cmd.replace("`", "").replace("^", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def _segments(cmd: str) -> List[str]:
    return [p.strip() for p in re.split(r"\|\||&&|[|;&\n]", cmd) if p.strip()]


def _segment_safe(seg: str) -> bool:
    seg = seg.lstrip(". ").strip()
    if not seg:
        return True
    tok, _, rest = seg.partition(" ")
    tok = tok.removesuffix(".exe")
    rest = rest.strip()
    if tok in _SAFE_ARGS:
        return _SAFE_ARGS[tok](rest)
    if tok.startswith("get-") and tok not in _UNSAFE_GET:
        return True
    return tok in _SAFE_COMMANDS


def classify_command(command: str) -> Tuple[str, str]:
    """Return ``(verdict, reason)`` for a shell command string."""
    raw = (command or "").strip()
    if not raw:
        return "deny", "empty command"
    if len(raw) > MAX_COMMAND_CHARS:
        return "deny", "command too long"
    norm = _normalize(raw)
    for rx, why in _DENY_RE:
        if rx.search(norm):
            return "deny", why
    # Scriptblocks, subexpressions and redirects can hide arbitrary actions.
    if re.search(r"[{}]|\$\(|@\(|\(", norm):
        return "confirm", "contains scriptblock or subexpression"
    if re.search(r">(?!\s*\$null)(?!&1)", norm):
        return "confirm", "writes output to a file"
    if all(_segment_safe(s) for s in _segments(norm)):
        return "allow", "read-only command"
    return "confirm", "command can change system state"
