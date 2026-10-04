"""Offline demo: run the REAL matching + dedup + digest pipeline on a simulated
feed of channel posts — no Telegram account, no login, no network needed.

    python main.py demo        # writes demo_preview.html

The simulated feed deliberately contains: keyword matches, excluded spam
(betting ad with the word "free"), the same viral link reposted across three
channels (with different UTM params + www/trailing-slash variants), a verbatim
repost (text-hash dedup), a media-only post, and plain noise.
"""
from __future__ import annotations

import zlib
from datetime import datetime
from pathlib import Path

from .dedupe import Clusters, cluster_key
from .digest import build_messages, message_link

# (channel title, @username or None for private, text, urls)
FEED: list[tuple[str, str | None, str, list[str]]] = [
    ("AI Insider",   "ai_insider",   "OpenAI just released GPT-5 with real-time video understanding. The demos are unreal 🤯", ["https://futurenews.io/gpt5-launch?utm_source=tg"]),
    ("Tech Daily",   "techdaily",    "🚨 GPT-5 is here: OpenAI's new model understands live video. Full breakdown 👇", ["https://futurenews.io/gpt5-launch?utm_medium=social"]),
    ("News Hub",     "newshub24",    "Big AI day: OpenAI releases GPT-5 — full coverage", ["https://www.futurenews.io/gpt5-launch/"]),
    ("Dev Corner",   "devcorner",    "Just published: parse-pdf, an open source Python library that beats every commercial parser. GitHub link below ⭐", ["https://github.com/devcorner/parse-pdf"]),
    ("Habesha Tech", "habeshatech",  "Ethio telecom fires up its first 5G sites in Addis Ababa — coverage map inside", []),
    ("Abyssinia Update", None,       "Ethio telecom fires up its first 5G sites in Addis Ababa — coverage map inside", []),
    ("Bet Palace",   "betpalace",    "🎰 FREE 500% first deposit bonus! Best casino odds, instant payout. Join & win big TODAY", ["https://spam.example.com/bonus"]),
    ("Free Stuff Daily", "freestuffdaily", "🎓 UDEMY: Complete Python Bootcamp — 100% off coupon, next 48 hours only!", ["https://deals.example.com/udemy-python"]),
    ("Random Vlogs", "dailyvlog",    "new vlog just dropped on my channel, link in comments ❤️", []),
    ("Foodies Club", "foodclub",     "Sunday special: homemade shiro in 20 minutes, recipe below 🍲", []),
    ("Meme Zone",    "memezone",     "", []),  # media-only post
    ("SaaS Deals",   "saasdeals",    "Free 6 months of Notion Plus for students — grab it before it expires", ["https://aff.example.com/notion-plus?ref=abc&utm_campaign=x"]),
    ("Free Stuff Daily", "freestuffdaily", "Notion Plus free for 6 months — student promo is back!", ["https://aff.example.com/notion-plus"]),
    ("News Hub",     "newshub24",    "BREAKING: Regulators in the EU announce new AI safety rules — what changes for users", []),
    ("Tech Daily",   "techdaily",    "Apple acquires a drone startup for $900M — biggest buy of the year, insiders say", []),
    ("Meme Zone",    "memezone",     "that feeling when monday hits 😂", []),
    ("Daily Motivation", "motivate", "Don't watch the clock; do what it does. Keep going. 💪", []),
    ("Footy Fans",   "footyfans",    "Match tonight 21:00 EAT — who's winning? Drop your score predictions 👇", []),
    ("Dev Corner",   "devcorner",    "PSA: update to the latest Docker release patches a nasty container escape — patch now", []),
    ("Random Vlogs", "dailyvlog",    "sunset from my balcony today 🌇", []),
    ("Habesha Tech", "habeshatech",  "Addis Ababa hosts the Africa Tech summit next month — 200+ startups confirmed", []),
    ("AI Insider",   "ai_insider",   "Researchers show a small neural network solving tasks once thought to need LLMs — paper thread 🧵", ["https://arxiv.org/abs/2401.99999"]),
    ("Trading Hub",  "tradehub",     "BTC breaks resistance with a volume spike — chart 📈", []),
    ("Foodies Club", "foodclub",     "poll: what's the top kitfo spot in town? 🥩", []),
]


def _cid(title: str) -> int:
    """Stable fake channel id for demo links."""
    return 1_000_000_000 + zlib.crc32(title.encode()) % 9_000_000_000


def _short(text: str, n: int = 58) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def run_demo(matcher, topics, out_path: str = "demo_preview.html") -> None:
    print("\n🔬 DEMO — simulated run over a fake 24h feed (real pipeline, no login)\n")
    clusters, seen_state = Clusters(), set()   # seen_state = previous digests (empty)
    stats = {"channels": len({f[0] for f in FEED}), "messages": 0, "matched": 0, "unique": 0}

    for i, item in enumerate(FEED, start=1):
        title, uname, text, urls = item[0], item[1], item[2], item[3]
        stats["messages"] += 1
        pad = f"{i:>2}. {title[:16]:<16}"
        if not text.strip():
            print(f"{pad} ⏭  media-only post — skipped")
            continue
        matches = matcher.match(text)
        if not matches:
            print(f"{pad} ⏭  no match — \"{_short(text, 44)}\"")
            continue
        key = cluster_key(text, urls)
        if key in seen_state:
            print(f"{pad} ⏭  already in a previous digest")
            continue
        topic, score, via = matches[0]
        dup = key in clusters.items

        # Mock engagement metrics for demo
        views = 1500 + (i * 2400) % 35000
        forwards = 40 + (i * 85) % 1200
        reactions = 15 + (i * 42) % 500
        age_hours = max(0.5, i * 0.75)
        velocity = (forwards * 3 + reactions * 2 + views) / (age_hours ** 1.2)
        is_viral = velocity >= 150.0

        clusters.add(
            key, topic=topic.name, score=score, via=via,
            channel_title=title,
            link=message_link(uname, _cid(title), i),
            text=text,
            other_topics=[t.name for t, _, _ in matches[1:]],
            views=views, forwards=forwards, reactions=reactions,
            velocity=velocity, is_viral=is_viral,
        )
        stats["matched"] += 1
        if dup:
            print(f"{pad} 🔁 duplicate — merged into existing item (seen in N channels)")
        else:
            print(f"{pad} ✅ matched → {topic.name}{' 🤖' if via == 'ai' else ''}{' 🔥' if is_viral else ''}")

    fresh = clusters.all()
    stats["unique"] = len(fresh)

    # If Groq / LLM key is configured, run LLM batch reasoning on demo items
    from .config import load_settings
    from .matching import LLMClassifier
    s = load_settings()
    llm = LLMClassifier(
        provider=s.llm_provider,
        api_key=s.groq_api_key or s.openai_api_key,
        base_url=s.llm_base_url,
        model=s.llm_model,
    )
    if llm.available() and fresh:
        print(f"\n🧠 Running Groq LLM reasoning & 1-sentence summarization ({s.llm_model})...")
        llm_items = [
            {"id": i, "text": c["best"].get("text_raw") or c["best"]["snippet"], "topic": c["best"]["topic"]}
            for i, c in enumerate(fresh)
        ]
        llm_results = llm.process_batch(llm_items, topics)
        res_by_id = {r["id"]: r for r in llm_results if isinstance(r, dict) and "id" in r}

        valid_topic_names = {t.name for t in topics}
        refined_fresh = []
        for i, c in enumerate(fresh):
            r = res_by_id.get(i)
            if r:
                cat = str(r.get("category") or "").strip()
                qual = int(r.get("quality", 10))
                summary = str(r.get("summary") or "").strip()
                if cat.upper() == "NONE" or qual < 3:
                    print(f"   🚫 LLM filtered out noise: {c['best']['snippet']}")
                    continue
                if cat in valid_topic_names:
                    if cat != c["best"]["topic"]:
                        print(f"   🔀 LLM reclassified: '{c['best']['snippet'][:35]}...' -> {cat}")
                    c["best"]["topic"] = cat
                if summary:
                    c["best"]["summary"] = summary
            refined_fresh.append(c)
        fresh = refined_fresh
        stats["unique"] = len(fresh)

    messages = build_messages(datetime.now(), stats, fresh, topics, viral_threshold=150.0, show_metrics=True)
    Path(out_path).write_text(_render_html(messages), encoding="utf-8")

    print(f"""
────────────────────────────────────────────────────────────
📊 Scanned {stats['channels']} channels · {stats['messages']} posts
✅ {stats['matched']} matches → {stats['unique']} unique items after dedup
📄 Telegram-styled preview written to: {out_path}
   Open it in the file viewer — that's what lands in your digest channel.
────────────────────────────────────────────────────────────
""")


_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0e1621;display:flex;justify-content:center;padding:26px 12px;
     font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
.chat{width:100%;max-width:540px}
.topbar{display:flex;gap:12px;align-items:center;padding:4px 8px 12px}
.avatar{width:46px;height:46px;border-radius:50%;background:#2b5278;display:flex;
        align-items:center;justify-content:center;font-size:22px}
.meta .t{color:#fff;font-weight:600;font-size:15.5px}
.meta .s{color:#7f91a4;font-size:12.5px;margin-top:2px}
.datepill{display:flex;justify-content:center;margin:4px 0 8px}
.datepill span{background:#1c2a3a;color:#8aa0b4;font-size:12px;padding:4px 12px;border-radius:12px}
.msg{background:#182533;border-radius:12px;border-top-left-radius:4px;padding:10px 12px 8px;
     margin:8px 0;color:#e7ebf0;font-size:14.5px;line-height:1.5;max-width:88%;
     box-shadow:0 1px 1px rgba(0,0,0,.4);overflow-wrap:anywhere}
.msg a{color:#71b8ff;text-decoration:none}
.msg b{color:#fff}
.msg .time{display:block;text-align:right;color:#5f7387;font-size:11px;margin-top:2px}
.foot{color:#5f7387;font-size:12px;text-align:center;margin:16px 0 4px;line-height:1.5}
"""


def _render_html(messages: list[str]) -> str:
    now = datetime.now()
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>tdigest — demo digest preview</title><style>", _CSS, "</style></head><body>",
        "<div class='chat'>",
        "<div class='topbar'><div class='avatar'>🗞</div><div class='meta'>",
        "<div class='t'>My Daily Digest</div>",
        "<div class='s'>private channel · delivered by tdigest</div></div></div>",
        "<div class='datepill'><span>", now.strftime("%B %d, %Y"), "</span></div>",
    ]
    for m in messages:
        parts.append("<div class='msg'>")
        parts.append(m.replace("\n", "<br>"))
        parts.append(f"<span class='time'>{now:%H:%M}</span></div>")
    parts.append(
        "<div class='foot'>Demo render — the real digest is delivered by your own "
        "Telegram account into your private digest channel.<br>Generated by 🤖 tdigest</div>"
    )
    parts.append("</div></body></html>")
    return "".join(parts)
