"""Load runtime settings (.env) and interest topics (interests.yaml)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    return default if v in (None, "") else int(v)


def _float(name: str, default: float) -> float:
    v = os.getenv(name)
    return default if v in (None, "") else float(v)


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name, "").strip().lower()
    return default if v == "" else v in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # --- Telegram credentials (required) ---
    api_id: int
    api_hash: str
    phone: str | None
    session_path: str
    # --- digest behaviour ---
    digest_channel_title: str
    digest_time: str
    sleep_between_channels: float
    max_messages_per_channel: int
    first_run_lookback_hours: int
    lookback_cap_hours: int
    include_media_only: bool
    send_empty_digest: bool
    send_silent: bool
    state_path: str
    interests_path: str
    scan_concurrency: int
    viral_threshold: float
    show_engagement_metrics: bool
    # --- AI matching & LLM summarization ---
    ai_provider: str          # off | openai | local
    openai_api_key: str | None
    openai_base_url: str
    embedding_model: str
    groq_api_key: str | None
    llm_provider: str         # groq | openai | off
    llm_model: str
    llm_base_url: str


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        api_id=_int("TG_API_ID", 0),
        api_hash=os.getenv("TG_API_HASH", "").strip(),
        phone=os.getenv("TG_PHONE") or None,
        session_path=os.getenv("SESSION_PATH", "session/tdigest"),
        digest_channel_title=os.getenv("DIGEST_CHANNEL_TITLE", "My Daily Digest"),
        digest_time=os.getenv("DIGEST_TIME", "08:00"),
        sleep_between_channels=_float("SLEEP_BETWEEN_CHANNELS", 0.5),
        max_messages_per_channel=_int("MAX_MESSAGES_PER_CHANNEL", 400),
        first_run_lookback_hours=_int("FIRST_RUN_LOOKBACK_HOURS", 24),
        lookback_cap_hours=_int("LOOKBACK_CAP_HOURS", 72),
        include_media_only=_bool("INCLUDE_MEDIA_ONLY", False),
        send_empty_digest=_bool("SEND_EMPTY_DIGEST", False),
        send_silent=_bool("SEND_SILENT", False),
        state_path=os.getenv("STATE_PATH", "tdigest.db"),
        interests_path=os.getenv("INTERESTS_PATH", "interests.yaml"),
        scan_concurrency=_int("SCAN_CONCURRENCY", 3),
        viral_threshold=_float("VIRAL_THRESHOLD", 150.0),
        show_engagement_metrics=_bool("SHOW_ENGAGEMENT_METRICS", True),
        ai_provider=os.getenv("AI_PROVIDER", "local").strip().lower(),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "").strip(),
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        llm_provider=os.getenv("LLM_PROVIDER", "groq" if os.getenv("GROQ_API_KEY") else "off").strip().lower(),
        llm_model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile").strip(),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
    )


@dataclass
class Topic:
    name: str
    keywords: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    description: str = ""
    threshold: float = 0.35


def load_interests(path: str) -> tuple[dict, list[Topic]]:
    """Return (settings_block, topics) from interests.yaml."""
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    cfg = data.get("settings", {}) or {}
    topics: list[Topic] = []
    for t in data.get("topics", []) or []:
        topics.append(Topic(
            name=str(t["name"]),
            keywords=[str(k) for k in (t.get("keywords") or [])],
            exclude=[str(k) for k in (t.get("exclude") or [])],
            description=str(t.get("description") or "").strip(),
            threshold=float(t.get("threshold", cfg.get("threshold", 0.35))),
        ))
    return cfg, topics
