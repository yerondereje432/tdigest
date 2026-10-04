"""Render the digest as one or more HTML messages (Telegram limit: 4096 chars).

No block is ever split across messages, so links/markup stay intact.
"""
from __future__ import annotations

import html
from datetime import datetime


def message_link(username: str | None, channel_id: int, msg_id: int) -> str:
    """Direct link to a post. t.me/c/<id>/<msg> works for private channels."""
    if username:
        return f"https://t.me/{username}/{msg_id}"
    return f"https://t.me/c/{channel_id}/{msg_id}"


def compact_number(n: int) -> str:
    """Format 1234 -> 1.2K, 1500000 -> 1.5M."""
    if not n or n < 0:
        return "0"
    if n >= 1_000_000:
        val = n / 1_000_000
        return f"{val:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        val = n / 1_000
        return f"{val:.1f}K".replace(".0K", "K")
    return str(n)


def snippet(text: str, limit: int = 110) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def _header(now: datetime, stats: dict) -> str:
    return (
        f"<b>🗞 Your Daily Digest — {now:%a, %d %b %Y}</b>\n\n"
        f"Scanned <b>{stats.get('channels', 0)}</b> channels · "
        f"<b>{stats.get('messages', 0)}</b> posts\n"
        f"✅ <b>{stats.get('matched', 0)}</b> matches → "
        f"<b>{stats.get('unique', 0)}</b> unique items\n"
    )


def _item_line(c: dict, viral_threshold: float = 150.0, show_metrics: bool = True) -> str:
    b = c["best"]
    velocity = b.get("velocity", 0.0)
    is_viral = b.get("is_viral", False) or (velocity >= viral_threshold)

    disp_text = html.escape(b.get("summary") or b["snippet"])

    parts = [
        f"• <a href=\"{b['link']}\">{html.escape(b['channel_title'])}</a>"
        f" — {disp_text}"
    ]
    if b.get("summary") and b.get("via") != "ai":
        parts.append(" 🤖")
    if is_viral:
        parts.append(" 🔥")
    if len(c["channels"]) > 1:
        parts.append(f" <i>(seen in {len(c['channels'])} channels)</i>")
    if b.get("via") == "ai":
        parts.append(" 🤖")
    if b.get("other_topics"):
        parts.append(
            " <i>also: " + ", ".join(html.escape(t) for t in b["other_topics"]) + "</i>"
        )
    if show_metrics:
        views = b.get("views", 0)
        forwards = b.get("forwards", 0)
        reactions = b.get("reactions", 0)
        if views > 0 or forwards > 0 or reactions > 0:
            m_parts = []
            if views > 0:
                m_parts.append(f"👁 {compact_number(views)}")
            if forwards > 0:
                m_parts.append(f"🔁 {compact_number(forwards)}")
            if reactions > 0:
                m_parts.append(f"❤️ {compact_number(reactions)}")
            parts.append(f" <i>({' · '.join(m_parts)})</i>")
    return "".join(parts) + "\n"


def build_messages(now: datetime, stats: dict, clusters: list[dict],
                   topics, max_chars: int = 3500,
                   viral_threshold: float = 150.0,
                   show_metrics: bool = True) -> list[str]:
    groups: dict[str, list[dict]] = {}
    for c in clusters:
        groups.setdefault(c["best"]["topic"], []).append(c)
    order = [t.name for t in topics]
    names = [n for n in order if n in groups] + sorted(n for n in groups if n not in order)

    blocks = [_header(now, stats)]
    if not clusters:
        blocks.append("\n<i>Nothing new matched your interests today.</i>\n")
    for name in names:
        items = sorted(
            groups[name],
            key=lambda c: (-c["best"].get("velocity", 0.0), -len(c["channels"]), -c["best"]["score"])
        )
        blocks.append(f"\n<b>{html.escape(name)}</b> — {len(items)}\n")
        blocks.extend(_item_line(c, viral_threshold, show_metrics) for c in items)

    messages, cur = [], ""
    for b in blocks:
        if cur and len(cur) + len(b) > max_chars:
            messages.append(cur)
            cur = b
        else:
            cur += b
    if cur:
        messages.append(cur)
    return messages
