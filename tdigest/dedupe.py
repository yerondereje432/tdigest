"""Deduplication of the same content reposted across many channels.

Cluster key = normalized primary URL if the post has links (tracking
parameters stripped), otherwise a hash of the normalized text.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .digest import snippet

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)

_DROP_PARAMS = {"fbclid", "gclid", "ref", "ref_src", "spm", "igshid", "si"}
_DROP_PREFIXES = ("utm_",)

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_url(u: str) -> str:
    u = (u or "").strip().rstrip(".,);]")
    if not u:
        return ""
    try:
        p = urlsplit(u)
    except ValueError:
        return ""
    scheme = (p.scheme or "https").lower()
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    qs = [
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in _DROP_PARAMS and not k.lower().startswith(_DROP_PREFIXES)
    ]
    path = p.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, urlencode(qs), ""))


def text_key(text: str, n: int = 220) -> str:
    t = _WS.sub(" ", _PUNCT.sub("", (text or "").lower())).strip()
    return hashlib.sha1(t[:n].encode()).hexdigest()


def cluster_key(text: str, urls: list[str]) -> str:
    norm = [u for u in (normalize_url(u) for u in urls) if u]
    if norm:
        return "url:" + min(norm)  # canonical: lexicographically smallest URL
    return "txt:" + text_key(text)


class Clusters:
    """Groups duplicate matches; keeps the highest-scoring post as representative."""

    def __init__(self):
        self.items: dict[str, dict] = {}

    def add(self, key, *, topic, score, via, channel_title, link, text,
            other_topics, views=0, forwards=0, reactions=0, velocity=0.0, is_viral=False):
        c = self.items.get(key)
        if c is None:
            c = self.items[key] = {
                "key": key, "channels": set(), "count": 0,
                "best": None, "max_views": 0,
            }
        c["count"] += 1
        c["channels"].add(channel_title)
        c["max_views"] = max(c["max_views"], views or 0)
        current_best = c["best"]
        if (
            current_best is None
            or velocity > current_best.get("velocity", 0.0)
            or (velocity == current_best.get("velocity", 0.0) and score > current_best["score"])
        ):
            c["best"] = {
                "topic": topic, "score": score, "via": via,
                "channel_title": channel_title, "link": link,
                "snippet": snippet(text),
                "text_raw": text,
                "other_topics": list(other_topics or []),
                "views": views or 0,
                "forwards": forwards or 0,
                "reactions": reactions or 0,
                "velocity": velocity or 0.0,
                "is_viral": is_viral,
            }

    def all(self) -> list[dict]:
        return list(self.items.values())
