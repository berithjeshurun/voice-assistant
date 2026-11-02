"""Parse assistant / SERP text into HUD cards for the web surface."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from amy.protocol.messages import HudCard

_URL_RE = re.compile(r"https?://[^\s\]\)<>\"']+")
# Numbered hit ending at a URL (Hive SERP dumps are often one long line)
_HIT_RE = re.compile(
    r"(?:^|[\s])(\d+)\.\s+(.+?)\s+(https?://[^\s\]\)<>\"']+)",
    re.S,
)


def _clean_title(title: str) -> str:
    t = re.sub(r"\s+", " ", (title or "")).strip(" -–—\n\t")
    t = re.sub(r"\s+\[[0-9]{4}-[0-9]{2}-[0-9]{2}\].*$", "", t).strip(" -–—")
    # Drop duplicated "Title - Source Title Source" tails
    if " - " in t and len(t) > 90:
        head = t.split(" - ", 1)[0].strip()
        if len(head) >= 8:
            t = head
    return t[:160]


def cards_from_serp_text(text: str, *, limit: int = 6) -> List[HudCard]:
    """Extract web result cards from raw agent SERP / answer text."""
    raw = (text or "").strip()
    if not raw:
        return []
    low = raw.lower()
    looks_serp = (
        "search results for" in low
        or "web results for" in low
        or bool(_HIT_RE.search(raw))
        or (bool(_URL_RE.search(raw)) and bool(re.search(r"\b\d+\.\s+\S", raw)))
    )
    if not looks_serp:
        return []

    cards: List[HudCard] = []
    seen: set[str] = set()
    for m in _HIT_RE.finditer(raw):
        title = _clean_title(m.group(2) or "")
        url = (m.group(3) or "").rstrip(".,);]")
        if not url or url in seen:
            continue
        # Skip header junk mistaken as title
        if title.lower().startswith(("web results for", "search results for")):
            # Keep only the bit after the last "N." fragment if present
            inner = re.search(r"\d+\.\s+(.+)$", title)
            title = _clean_title(inner.group(1)) if inner else title
        if title.lower().startswith(("web results for", "search results for")):
            title = url
        seen.add(url)
        cards.append(HudCard(kind="web", title=title or url[:80], url=url, snippet=""))
        if len(cards) >= limit:
            return cards

    if not cards:
        for url in _URL_RE.findall(raw)[:limit]:
            url = url.rstrip(".,);]")
            if url in seen:
                continue
            seen.add(url)
            cards.append(HudCard(kind="web", title=url[:80], url=url, snippet=""))
    return cards


def cards_from_turn(
    assistant_text: str,
    *,
    meta: Dict[str, Any] | None = None,
    limit: int = 6,
) -> List[HudCard]:
    """Prefer structured meta hits; else parse assistant SERP text."""
    meta = meta or {}
    structured = meta.get("web_hits") or meta.get("search_hits") or meta.get("cards")
    out: List[HudCard] = []
    if isinstance(structured, list):
        for item in structured[:limit]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "").strip()
            url = str(item.get("url") or item.get("link") or "").strip()
            snippet = str(
                item.get("snippet") or item.get("body") or item.get("description") or ""
            ).strip()
            if not title and not url:
                continue
            out.append(
                HudCard(
                    kind="web",
                    title=(title or url)[:160],
                    url=url,
                    snippet=snippet[:220],
                )
            )
        if out:
            return out
    return cards_from_serp_text(assistant_text, limit=limit)


__all__ = ["cards_from_serp_text", "cards_from_turn"]
