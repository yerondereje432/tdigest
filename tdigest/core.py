"""Core engine: read your channels, match interests, dedupe, send the digest."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient, errors, events, functions, types, utils

from .dedupe import URL_RE, Clusters, cluster_key
from .digest import build_messages, message_link
from .state import State

log = logging.getLogger("tdigest")


def make_client(s) -> TelegramClient:
    Path(s.session_path).parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        s.session_path, s.api_id, s.api_hash,
        device_model="tdigest", system_version="1.0", app_version="1.0",
    )


def msg_urls(m) -> list[str]:
    """URLs found in the text plus hidden URLs behind formatted links."""
    urls = set(URL_RE.findall(m.raw_text or ""))
    for ent in m.entities or []:
        if isinstance(ent, types.MessageEntityTextUrl) and ent.url:
            urls.add(ent.url)
    return sorted(urls)


async def my_channels(client, include_groups: bool = False) -> list:
    """Every broadcast channel the account has joined (public or private)."""
    out = []
    async for d in client.iter_dialogs():
        e = d.entity
        if isinstance(e, types.Channel) and (e.broadcast or (include_groups and e.megagroup)):
            out.append(e)
    return out


async def ensure_digest_channel(client, title: str):
    """Find the digest channel by title; create a private one if missing."""
    title_l = title.strip().lower()
    async for d in client.iter_dialogs():
        e = d.entity
        if isinstance(e, types.Channel) and e.broadcast \
                and (e.title or "").strip().lower() == title_l:
            return e
    try:
        log.info("Creating private channel %r for digests", title)
        res = await client(functions.channels.CreateChannelRequest(
            title=title, about="Automated daily digest (tdigest)", broadcast=True))
        return res.chats[0]
    except errors.RPCError as e:
        log.warning("Could not create channel (%s) — falling back to Saved Messages", e)
        return "me"


async def collect(client, entity, state, s, matcher, clusters, stats, lock=None) -> None:
    """Read one channel's new messages and feed matching ones into clusters."""
    if state.is_muted(entity.id):
        log.info("Skipping muted channel '%s'", utils.get_display_name(entity))
        return

    now = datetime.now(timezone.utc)
    cursor = state.get_cursor(entity.id)
    lookback = s.first_run_lookback_hours if not cursor else s.lookback_cap_hours
    cutoff = now - timedelta(hours=lookback)
    newest = cursor
    title = utils.get_display_name(entity)
    local_msg_count = 0
    local_matched_count = 0

    try:
        async for m in client.iter_messages(entity, limit=s.max_messages_per_channel):
            # iter_messages walks newest -> oldest: stop at cursor or time cap
            if m.id <= cursor or (m.date and m.date < cutoff):
                break
            newest = max(newest, m.id)
            if getattr(m, "action", None):  # service message (joins, pins…)
                continue
            local_msg_count += 1
            text = (m.raw_text or "").strip()
            if not text:
                continue  # media-only post: nothing to match against
            matches = matcher.match(text)
            if not matches:
                continue
            key = cluster_key(text, msg_urls(m))
            if state.is_seen(key):
                continue  # already included in a previous digest

            views = getattr(m, "views", 0) or 0
            forwards = getattr(m, "forwards", 0) or 0
            reactions = 0
            if getattr(m, "reactions", None) and getattr(m.reactions, "results", None):
                reactions = sum(getattr(r, "count", 0) or 0 for r in m.reactions.results)

            age_hours = 1.0
            if m.date:
                msg_date = m.date if m.date.tzinfo else m.date.replace(tzinfo=timezone.utc)
                age_hours = max((now - msg_date).total_seconds() / 3600.0, 0.5)

            velocity = (forwards * 3 + reactions * 2 + views) / (age_hours ** 1.2)
            is_viral = velocity >= s.viral_threshold

            topic, score, via = matches[0]

            item_kwargs = dict(
                key=key, topic=topic.name, score=score, via=via,
                channel_title=title,
                link=message_link(getattr(entity, "username", None), entity.id, m.id),
                text=text,
                other_topics=[t.name for t, _, _ in matches[1:]],
                views=views, forwards=forwards, reactions=reactions,
                velocity=velocity, is_viral=is_viral,
            )

            if lock:
                async with lock:
                    clusters.add(**item_kwargs)
            else:
                clusters.add(**item_kwargs)
            local_matched_count += 1
    except errors.FloodWaitError as fw:
        log.warning("FloodWait %ss on '%s' — sleeping it off", fw.seconds, title)
        await asyncio.sleep(fw.seconds + 1)
    except errors.RPCError as e:
        log.warning("Skipping '%s': %s", title, e)
    finally:
        if lock:
            async with lock:
                stats["messages"] += local_msg_count
                stats["matched"] += local_matched_count
        else:
            stats["messages"] += local_msg_count
            stats["matched"] += local_matched_count

        if newest:
            state.set_cursor(entity.id, newest)


async def run_once(client, s, matcher, topics) -> None:
    """One full digest run: scan all channels, build digest, deliver it."""
    state = State(s.state_path)
    try:
        digest_chat = await ensure_digest_channel(client, s.digest_channel_title)
        channels = await my_channels(client)
        log.info("Scanning %d channels (concurrency=%d)…", len(channels), s.scan_concurrency)
        clusters = Clusters()
        stats = {"channels": len(channels), "messages": 0, "matched": 0, "unique": 0}
        lock = asyncio.Lock()
        sem = asyncio.Semaphore(max(1, s.scan_concurrency))

        completed_count = 0

        async def worker(ch):
            nonlocal completed_count
            async with sem:
                await collect(client, ch, state, s, matcher, clusters, stats, lock=lock)
                async with lock:
                    completed_count += 1
                    log.info("[%3d/%d] %s", completed_count, len(channels), ch.title)
                await asyncio.sleep(s.sleep_between_channels)

        sorted_channels = sorted(channels, key=lambda c: (c.title or "").lower())
        await asyncio.gather(*[worker(ch) for ch in sorted_channels])

        fresh = clusters.all()
        stats["unique"] = len(fresh)

        if fresh:
            from .matching import LLMClassifier
            llm = LLMClassifier(
                provider=s.llm_provider,
                api_key=s.groq_api_key or s.openai_api_key,
                base_url=s.llm_base_url,
                model=s.llm_model,
            )
            if llm.available():
                log.info("Running LLM batch reasoning (%s / %s) on %d items...", s.llm_provider, s.llm_model, len(fresh))
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
                            log.info("LLM filtered out low-quality/off-topic item: %s", c["best"]["snippet"])
                            continue
                        if cat in valid_topic_names:
                            c["best"]["topic"] = cat
                        if summary:
                            c["best"]["summary"] = summary
                    refined_fresh.append(c)
                fresh = refined_fresh
                stats["unique"] = len(fresh)

        if not fresh and not s.send_empty_digest:
            log.info("Nothing new today — no digest sent")
            return
        messages = build_messages(
            datetime.now(), stats, fresh, topics,
            viral_threshold=s.viral_threshold,
            show_metrics=s.show_engagement_metrics
        )
        for msg in messages:
            await client.send_message(
                digest_chat, msg, parse_mode="html",
                link_preview=False, silent=s.send_silent,
            )
            await asyncio.sleep(0.7)
        state.mark_seen([c["key"] for c in fresh])
        state.save_posts(fresh)
        state.prune()
        log.info("✅ Digest sent: %d unique items in %d message(s)",
                 len(fresh), len(messages))
    finally:
        state.close()


def seconds_until(hhmm: str) -> float:
    """Seconds from now until the next local HH:MM."""
    h, m = map(int, hhmm.split(":"))
    now = datetime.now().astimezone()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def serve(client, s, matcher, topics) -> None:
    """Daemon loop: digest daily at DIGEST_TIME, or instantly on commands sent directly
    inside your private 'My Daily Digest' channel."""
    digest_chat = await ensure_digest_channel(client, s.digest_channel_title)
    manual = asyncio.Event()
    running = {"busy": False}

    @client.on(events.NewMessage(chats=digest_chat, pattern=r"(?i)^\s*!digest now\s*$"))
    async def _on_manual(_event):
        if running["busy"]:
            log.info("Manual trigger ignored — a run is already in progress")
        else:
            log.info("Manual trigger received from Digest Channel")
            manual.set()

    @client.on(events.NewMessage(chats=digest_chat, pattern=r"(?i)^\s*!(?:digest\s+query|query)\s+(.+)$"))
    async def _on_query(event):
        query_text = event.pattern_match.group(1).strip()
        log.info("AI RAG Query received: %r", query_text)
        reply_msg = await event.reply("🔍 <i>Searching 217 channels & generating AI response...</i>", parse_mode="html")
        
        state = State(s.state_path)
        try:
            posts = state.search_posts(query_text, limit=15)
            from .matching import LLMClassifier
            llm = LLMClassifier(
                provider=s.llm_provider,
                api_key=s.groq_api_key or s.openai_api_key,
                base_url=s.llm_base_url,
                model=s.llm_model,
            )
            if not llm.available():
                await reply_msg.edit("❌ AI RAG search requires GROQ_API_KEY or OPENAI_API_KEY in .env", parse_mode="html")
                return

            ans = llm.answer_query(query_text, posts)
            await reply_msg.edit(f"<b>🧠 AI Search Response:</b>\n\n{ans}", parse_mode="html", link_preview=False)
        except Exception as e:
            log.exception("Query handling failed: %s", e)
            await reply_msg.edit(f"❌ Error processing query: {e}", parse_mode="html")
        finally:
            state.close()

    @client.on(events.NewMessage(chats=digest_chat, pattern=r"(?i)^\s*!digest mute\s+(.+)$"))
    async def _on_mute(event):
        target = event.pattern_match.group(1).strip()
        state = State(s.state_path)
        try:
            found = False
            async for d in client.iter_dialogs():
                e = d.entity
                if isinstance(e, types.Channel):
                    if target.lower() in (e.title or "").lower() or target == str(e.id) or target == f"@{getattr(e, 'username', '')}":
                        state.mute_channel(e.id)
                        await event.reply(f"🔇 Muted channel: <b>{html.escape(e.title)}</b>", parse_mode="html")
                        found = True
                        break
            if not found:
                await event.reply(f"❌ Could not find channel matching '{html.escape(target)}'", parse_mode="html")
        finally:
            state.close()

    @client.on(events.NewMessage(chats=digest_chat, pattern=r"(?i)^\s*!digest unmute\s+(.+)$"))
    async def _on_unmute(event):
        target = event.pattern_match.group(1).strip()
        state = State(s.state_path)
        try:
            found = False
            async for d in client.iter_dialogs():
                e = d.entity
                if isinstance(e, types.Channel):
                    if target.lower() in (e.title or "").lower() or target == str(e.id) or target == f"@{getattr(e, 'username', '')}":
                        state.unmute_channel(e.id)
                        await event.reply(f"🔊 Unmuted channel: <b>{html.escape(e.title)}</b>", parse_mode="html")
                        found = True
                        break
            if not found:
                await event.reply(f"❌ Could not find channel matching '{html.escape(target)}'", parse_mode="html")
        finally:
            state.close()

    log.info("tdigest daemon started. Daily digest at %s (system local time).", s.digest_time)
    log.info("Tip: send '!digest now' or '!query <question>' in your 'My Daily Digest' channel.")
    while True:
        manual.clear()
        wait_s = seconds_until(s.digest_time)
        log.info("Next scheduled run in %.1f h", wait_s / 3600)
        try:
            await asyncio.wait_for(manual.wait(), timeout=wait_s)
        except asyncio.TimeoutError:
            pass
        running["busy"] = True
        started = datetime.now()
        try:
            await run_once(client, s, matcher, topics)
        except Exception:
            log.exception("Digest run failed — will retry on the next schedule")
        finally:
            running["busy"] = False
        log.info("Run finished in %s", datetime.now() - started)
