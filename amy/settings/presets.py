"""Chip-friendly presets (no long freeform text areas)."""

from __future__ import annotations

from typing import Any, Dict, List

# Assistant speaking / behavior tone — applied as a short prompt block.
PERSONA_PRESETS: List[Dict[str, str]] = [
    {
        "id": "warm",
        "label": "Warm",
        "blurb": "Friendly, supportive, lightly conversational.",
        "prompt": "Tone: warm and supportive. Keep replies short and human.",
    },
    {
        "id": "concise",
        "label": "Concise",
        "blurb": "Short answers, minimal fluff.",
        "prompt": "Tone: concise. Prefer one or two sentences unless asked for detail.",
    },
    {
        "id": "pro",
        "label": "Professional",
        "blurb": "Clear, formal, business-ready.",
        "prompt": "Tone: professional and precise. No slang.",
    },
    {
        "id": "playful",
        "label": "Playful",
        "blurb": "Light wit, still helpful.",
        "prompt": "Tone: lightly playful. Stay useful; never rude.",
    },
    {
        "id": "tech",
        "label": "Technical",
        "blurb": "Engineer-mode: exact and structured.",
        "prompt": "Tone: technical. Prefer exact names, paths, and steps.",
    },
]

CLEARANCE_ROLES = ["guest", "user", "trusted", "admin", "owner"]
CLEARANCE_LABELS = ["public", "internal", "confidential", "restricted"]

VOICE_STYLES = [
    "raw",
    "talk",
    "natural",
    "calm",
    "soft",
    "crisp",
    "bright",
    "radio",
    "piper",
]


def persona_preset(preset_id: str) -> Dict[str, Any]:
    pid = (preset_id or "").strip().lower()
    for p in PERSONA_PRESETS:
        if p["id"] == pid:
            return dict(p)
    return dict(PERSONA_PRESETS[0])


# Built-in webservice integration catalog (API keys stored in secrets files).
INTEGRATION_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "openai",
        "name": "OpenAI",
        "kind": "llm",
        "keys": ["OPENAI_API_KEY"],
        "docs": "https://platform.openai.com/api-keys",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "kind": "llm",
        "keys": ["ANTHROPIC_API_KEY"],
        "docs": "https://console.anthropic.com/",
    },
    {
        "id": "openweather",
        "name": "OpenWeather",
        "kind": "weather",
        "keys": ["OPENWEATHER_API_KEY"],
        "docs": "https://openweathermap.org/api",
    },
    {
        "id": "github",
        "name": "GitHub",
        "kind": "dev",
        "keys": ["GITHUB_TOKEN"],
        "docs": "https://github.com/settings/tokens",
    },
    {
        "id": "homeassistant",
        "name": "Home Assistant",
        "kind": "home",
        "keys": ["HA_URL", "HA_TOKEN"],
        "docs": "http://homeassistant.local:8123",
    },
    {
        "id": "smartpanels",
        "name": "SmartPanels",
        "kind": "home",
        "keys": ["SMARTPANELS_USER", "SMARTPANELS_PASSWORD", "SMARTPANELS_BASE_URL"],
        "docs": "https://smartpanel.ssevsoftsols.co.in",
        "pack": "smartpanels",
    },
    {
        "id": "serpapi",
        "name": "SerpAPI",
        "kind": "search",
        "keys": ["SERPAPI_API_KEY"],
        "docs": "https://serpapi.com/",
    },
    {
        "id": "elevenlabs",
        "name": "ElevenLabs",
        "kind": "voice",
        "keys": ["ELEVENLABS_API_KEY"],
        "docs": "https://elevenlabs.io/",
    },
]
