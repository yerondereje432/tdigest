# 🗞 tdigest — your personal Telegram channel digest

You're in **hundreds** of Telegram channels. You actually read… a few.
**tdigest** logs in as *you*, reads the last 24 hours of every channel you follow,
keeps only the posts that match your interests, deletes cross-channel duplicates,
and delivers **one clean daily digest** to a private channel — with direct links to the originals.

---

## ✨ Features

- 🧑‍💻 **Sees every channel you've joined** — public *and* private (it acts as your account, read-only)
- 🎯 **Hybrid matching** — keyword rules for hard includes/excludes **+** AI semantic scoring that catches paraphrases ("free course" matches a post saying "100% scholarship tutorial")
- 🧹 **Cross-channel dedup** — the same viral link reposted by 12 channels appears **once**, tagged *"(seen in 12 channels)"*
- 🔗 **Direct links** back to original posts, including private channels (`t.me/c/…`)
- ⏰ **Daily schedule** (you pick the time) **+** on-demand: send `!digest now` to your *Saved Messages*
- 🗄 **SQLite memory** — never digests the same post twice; survives restarts and downtime
- 🧘 **Polite with Telegram** — paces requests, handles `FloodWait` automatically, read-only
- ⚙️ **Everything is config** — no code edits needed to retarget it (great if you share/sell it)

## 👀 Instant offline preview (no login needed)

Want to see what you'll get — before connecting anything? The demo runs the
**real** matching, dedup and rendering pipeline over a simulated 24h feed
(spam, duplicates, media-only posts and noise included) and writes a
Telegram-styled preview page:

```bash
python main.py demo     # then open demo_preview.html
```

It's the fastest way to tune `interests.yaml` — and great for screenshots if
you share the project.

## 🤔 Why a userbot and not a "normal bot"?

Bots created with BotFather can only read channels where they're **added as admin** — they
cannot see *your* subscriptions. Reading your own channel list requires the account API
(MTProto), which is what [Telethon](https://github.com/LonamiWebs/Telethon) provides.
This tool only **reads** — it never joins, spams, or messages anyone — which keeps it
low-risk for your account.

## 🔄 How it works

```
your channels (hundreds)
   │  Telethon reads new messages since last run (paced, FloodWait-safe)
   ▼
HYBRID MATCHER ── per topic:   exclude keywords  →  reject
                               include keywords  →  instant match (score 1.0)
                               AI embedding ≥ threshold →  semantic match 🤖
   ▼
DEDUP ── same normalized URL (or text) across channels merges into one cluster
   ▼
DIGEST ── grouped by topic, sorted by virality, chunked under Telegram's 4096-char limit
   ▼
delivered to your private digest channel (auto-created if it doesn't exist)
```

## 🚀 Quick start

**Requirements:** Python 3.10+, a Telegram account.

1. **Get API credentials** (2 minutes): go to <https://my.telegram.org> → *API development tools* → create an app → copy `api_id` and `api_hash`.
2. **Install**
   ```bash
   cd telegram-digest
   python -m venv .venv && source .venv/bin/activate     # optional but recommended
   pip install -r requirements.txt
   # optional, for free local AI matching (~1-2 GB download once):
   pip install sentence-transformers
   ```
3. **Configure**
   ```bash
   cp .env.example .env        # fill in TG_API_ID, TG_API_HASH, TG_PHONE
   nano interests.yaml         # describe YOUR topics, keywords, exclusions
   ```
4. **One-time login** (Telegram sends you a code; asks for 2FA password if enabled)
   ```bash
   python main.py auth
   ```
5. **Try it immediately**
   ```bash
   python main.py channels     # sanity-check what will be scanned
   python main.py run          # build + deliver a digest right now
   ```
6. **Run it daily**
   ```bash
   python main.py serve        # digests daily at DIGEST_TIME; '!digest now' works too
   ```

## ⚙️ Configuration (.env)

| Variable | Default | Meaning |
|---|---|---|
| `TG_API_ID` / `TG_API_HASH` | — | **Required**, from my.telegram.org |
| `TG_PHONE` | — | Login phone, international format |
| `DIGEST_CHANNEL_TITLE` | `My Daily Digest` | Delivered here; auto-created as private channel |
| `DIGEST_TIME` | `08:00` | Daily run time (local time of the machine) |
| `AI_PROVIDER` | `local` | `off` = keywords only · `openai` = API embeddings · `local` = free on-device embeddings |
| `SLEEP_BETWEEN_CHANNELS` | `0.5` | Seconds; raise to `1–2` if you hit FloodWait |
| `MAX_MESSAGES_PER_CHANNEL` | `400` | Per-run per-channel cap |
| `FIRST_RUN_LOOKBACK_HOURS` | `24` | How far back the very first scan looks |
| `LOOKBACK_CAP_HOURS` | `72` | Max catch-up window after downtime |
| `SEND_EMPTY_DIGEST` | `false` | Send even when nothing matched |
| `SEND_SILENT` | `false` | No notification sound on delivery |

## 🎯 Tuning the matching (`interests.yaml`)

- **keywords** — exact word/phrase hits (word-boundary aware: `ai` won't match `said`). Instant inclusion.
- **exclude** — any hit kills the topic for that post (kills betting spam in "Deals", etc.).
- **description** — plain-English description the AI embeds once per run; posts scoring `≥ threshold` cosine similarity match semantically. Tagged with 🤖 in the digest.
- **threshold** — raise toward `0.45` if AI matches too much, lower toward `0.30` if it misses things.

Run `python main.py topics` to verify your config loads as expected, and
`python tests/smoke_test.py` to test the matching/dedup/rendering logic offline.

## 🖥 Running it 24/7

- **Your PC:** just leave `python main.py serve` running (use `tmux`/`screen` so it survives terminal close).
- **Raspberry Pi / VPS (incl. Oracle free tier):** copy the folder (including `.env` and `session/`) and run under systemd:

```ini
[Unit]
Description=tdigest daily Telegram digest
After=network-online.target

[Service]
WorkingDirectory=/home/you/telegram-digest
ExecStart=/home/you/telegram-digest/.venv/bin/python main.py serve
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

- **Docker** (one-command deploy to any VPS):

```bash
docker build -t tdigest .
# one-time interactive login:
docker run -it --rm --env-file .env \
    -v "$PWD/session:/app/session" -v "$PWD/data:/app/data" \
    tdigest python main.py auth
# then run the daemon forever:
docker run -d --name tdigest --restart unless-stopped --env-file .env \
    -v "$PWD/session:/app/session" -v "$PWD/data:/app/data" tdigest
```

## 🩹 Troubleshooting

| Symptom | Fix |
|---|---|
| `AuthKeyDuplicatedError` | Two copies share one session. Stop one, or delete `session/*.session` and re-run `auth`. |
| Constant `FloodWaitError` | Raise `SLEEP_BETWEEN_CHANNELS` to `1–2`; lower `MAX_MESSAGES_PER_CHANNEL`. |
| Nothing matches | `python main.py topics`; lower `threshold`; add keywords; check `AI_PROVIDER`. |
| Media-only posts missing | Expected — no text to match. `INCLUDE_MEDIA_ONLY` only affects counting. |
| Digest channel not found | It's auto-created on first run; check your channel list for `My Daily Digest`. |

## ⚖️ Safety & terms

This is **read-only personal software**: it never posts, joins, or contacts anyone.
Automating your own account sits near Telegram ToS boundaries — don't use it for spam,
respect rate limits (the defaults do), and you should be fine. Not affiliated with Telegram.

## 🗺 Roadmap ideas

- 📈 trend spikes: *"this topic exploded across your channels today"*
- 📊 weekly stats per channel/topic
- 🌐 tiny web dashboard for tuning topics
- 🔕 per-topic quiet hours

---

MIT licensed — personal use, respect Telegram's ToS. Built with [Telethon](https://github.com/LonamiWebs/Telethon).
