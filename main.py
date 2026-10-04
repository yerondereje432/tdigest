#!/usr/bin/env python3
"""tdigest — personal Telegram digest userbot.

Usage:
  python main.py auth       one-time login (phone + code + 2FA)
  python main.py run        build and send a digest right now
  python main.py serve      run forever: daily at DIGEST_TIME + '!digest now'
  python main.py demo       offline simulation: renders demo_preview.html (no login)
  python main.py channels   list the channels it will scan
  python main.py topics     show the interest topics loaded from interests.yaml
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

log = logging.getLogger("tdigest")


def _setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def _require_creds(s) -> None:
    if not s.api_id or not s.api_hash:
        sys.exit(
            "❌ Set TG_API_ID and TG_API_HASH in .env\n"
            "   Get them at https://my.telegram.org → API development tools → create app"
        )


def _load_all():
    from tdigest.config import load_interests, load_settings
    s = load_settings()
    icfg, topics = load_interests(s.interests_path)
    if not topics:
        log.warning("No topics found in %s — nothing will match!", s.interests_path)
    return s, icfg, topics


def _make_matcher(s, icfg, topics):
    from tdigest.matching import Embedder, Matcher
    embedder = None
    if s.ai_provider != "off":
        try:
            embedder = Embedder(
                s.ai_provider,
                api_key=s.openai_api_key,
                base_url=s.openai_base_url,
                model=s.embedding_model or None,
            )
            log.info("AI semantic matching: %s (%s)", s.ai_provider, embedder.model_name)
        except ValueError as e:
            log.warning("AI matching disabled: %s", e)
    return Matcher(topics, keyword_score=float(icfg.get("keyword_score", 1.0)),
                   embedder=embedder)


# --------------------------------------------------------------------------
def cmd_auth(s, _icfg, _topics):
    _require_creds(s)
    from tdigest.core import make_client

    async def go():
        client = make_client(s)
        await client.start(
            phone=s.phone or (lambda: input("Phone (international format, e.g. +2519…): "))
        )
        me = await client.get_me()
        print(f"\n✅ Logged in as {me.first_name or ''} (id {me.id})")
        print(f"   Session saved to '{s.session_path}.session' — keep it private!\n")
        await client.disconnect()

    asyncio.run(go())


async def _connect(s):
    from tdigest.core import make_client
    client = make_client(s)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        sys.exit("❌ Not logged in yet — run: python main.py auth")
    return client


def cmd_run(s, icfg, topics):
    _require_creds(s)
    from tdigest.core import run_once
    matcher = _make_matcher(s, icfg, topics)

    async def _go():
        client = await _connect(s)
        try:
            await run_once(client, s, matcher, topics)
        finally:
            await client.disconnect()

    asyncio.run(_go())


def cmd_serve(s, icfg, topics):
    _require_creds(s)
    from tdigest.core import serve
    matcher = _make_matcher(s, icfg, topics)

    async def _go():
        client = await _connect(s)
        try:
            await serve(client, s, matcher, topics)
        except KeyboardInterrupt:
            log.info("Stopped by user")
        finally:
            await client.disconnect()

    asyncio.run(_go())


def cmd_channels(s, _icfg, _topics):
    _require_creds(s)
    from tdigest.core import my_channels

    async def _go():
        client = await _connect(s)
        try:
            channels = await my_channels(client)
        finally:
            await client.disconnect()
        return channels

    channels = asyncio.run(_go())
    print(f"\n{len(channels)} channels will be scanned:\n")
    for ch in sorted(channels, key=lambda c: (c.title or "").lower()):
        uname = f"@{ch.username}" if getattr(ch, "username", None) else "private"
        print(f"  {ch.id:>13}  {ch.title}  ({uname})")


def cmd_topics(_s, icfg, topics):
    print(f"\nMatching settings: keyword_score={icfg.get('keyword_score', 1.0)}, "
          f"default threshold={icfg.get('threshold', 0.35)}\n")
    for t in topics:
        print(f"  {t.name}  (threshold {t.threshold})")
        if t.keywords:
            print(f"    keywords: {', '.join(t.keywords)}")
        if t.exclude:
            print(f"    exclude:  {', '.join(t.exclude)}")
        if t.description:
            print(f"    AI description: {t.description}")
        print()


def cmd_demo(s, icfg, topics):
    matcher = _make_matcher(s, icfg, topics)
    from tdigest.demo import run_demo
    run_demo(matcher, topics)


# --------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(prog="tdigest",
                                description="Personal Telegram digest userbot")
    p.add_argument("--debug", action="store_true", help="verbose logging")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("auth", "run", "serve", "channels", "topics", "demo"):
        sub.add_parser(name)
    args = p.parse_args()

    _setup_logging(args.debug)
    s, icfg, topics = _load_all()
    {
        "auth": cmd_auth,
        "run": cmd_run,
        "serve": cmd_serve,
        "channels": cmd_channels,
        "topics": cmd_topics,
        "demo": cmd_demo,
    }[args.cmd](s, icfg, topics)


if __name__ == "__main__":
    main()
