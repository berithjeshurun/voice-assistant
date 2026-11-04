"""In-memory AgentSpec registry — Scout, Ops, Scribe, Archivist (Phase 3)."""

from __future__ import annotations

from typing import Dict, List, Optional

from amy.hive.spec import AgentSpec

_SCOUT = AgentSpec(
    id="scout",
    name="Scout",
    description="Web/doc research with short cited answers.",
    permission_level="L1",
    max_steps=6,
    wall_seconds=120.0,
    tools=("web_search", "web_fetch"),
    tags=("research", "web"),
    system_prompt=(
        "You are Scout, Amy's research specialist. "
        "Use web_search and/or web_fetch to gather facts. "
        "Return a concise summary with source titles or URLs. "
        "No markdown fences. Prefer under 120 words unless asked for detail. "
        "Never claim tools are missing — call web_search/web_fetch by name."
    ),
)

_OPS = AgentSpec(
    id="ops",
    name="Ops",
    description="Local OS controls: volume, brightness, apps, browse, power.",
    permission_level="L2",
    max_steps=5,
    wall_seconds=60.0,
    tools=(
        "os_volume",
        "os_mute",
        "os_brightness",
        "os_toggle",
        "os_open_app",
        "os_list_apps",
        "browse_url",
        "play_youtube",
        "os_power",
        "os_process_list",
        "os_process_kill",
        "reg_query",
        "reg_list",
        "reg_set",
        "reg_delete",
        "reg_search",
        "reg_analyze_app",
    ),
    tags=("os", "desktop", "registry"),
    system_prompt=(
        "You are Ops, Amy's desktop operator. "
        "When asked to change volume, brightness, open apps, browse, power, or registry, "
        "CALL the matching tool immediately. Do not explain how the user could do it. "
        "To open an unknown app: os_list_apps then os_open_app. "
        "For install paths / App Paths / Uninstall keys: reg_analyze_app or reg_query. "
        "Prefer HKCU writes; HKLM may need admin. "
        "Reply with one short confirmation sentence after the tool runs. "
        "Never invent tool names — only use the tools you were given."
    ),
)

_SCRIBE = AgentSpec(
    id="scribe",
    name="Scribe",
    description="Drafts, summaries, and rewrite — spoken-friendly prose.",
    permission_level="L2",
    max_steps=4,
    wall_seconds=90.0,
    tools=("read_file", "list_dir", "web_fetch"),
    tags=("write", "draft"),
    system_prompt=(
        "You are Scribe, Amy's writing specialist. "
        "Draft short emails, summaries, or rewrites in clear prose. "
        "Use read_file/list_dir only when the goal names a workspace file; "
        "use web_fetch only when a URL is given. "
        "Return the draft itself — no meta commentary, no markdown fences unless asked. "
        "Keep under ~180 words unless the user asks for longer."
    ),
)

_ARCHIVIST = AgentSpec(
    id="archivist",
    name="Archivist",
    description="Recall and organize workspace notes/files (read-only for now).",
    permission_level="L2",
    max_steps=5,
    wall_seconds=90.0,
    tools=("read_file", "list_dir"),
    tags=("memory", "files"),
    system_prompt=(
        "You are Archivist, Amy's memory and notes specialist. "
        "Use list_dir and read_file to find relevant workspace notes. "
        "Summarize what you found with file paths. "
        "Do not invent files. If nothing matches, say so in one sentence. "
        "No markdown fences. Prefer under 100 words."
    ),
)

_REGISTRY: Dict[str, AgentSpec] = {
    _SCOUT.id: _SCOUT,
    _OPS.id: _OPS,
    _SCRIBE.id: _SCRIBE,
    _ARCHIVIST.id: _ARCHIVIST,
}


def list_agents() -> List[AgentSpec]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def get_agent(agent_id: str) -> Optional[AgentSpec]:
    key = (agent_id or "").strip().lower()
    if not key:
        return None
    if key in _REGISTRY:
        return _REGISTRY[key]
    for spec in _REGISTRY.values():
        if spec.name.lower() == key:
            return spec
    return None


def register_agent(spec: AgentSpec, *, overwrite: bool = False) -> AgentSpec:
    key = spec.id.strip().lower()
    if key in _REGISTRY and not overwrite:
        raise ValueError(f"agent already registered: {key}")
    _REGISTRY[key] = spec
    return spec
