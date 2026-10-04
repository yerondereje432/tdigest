"""Hybrid matching: keyword rules (hard include/exclude) + optional AI embeddings.

Keyword hits use word-boundary matching, so the keyword "ai" does NOT match
inside words like "said" or "again".
"""
from __future__ import annotations

import json
import logging
import math
import re
import urllib.request

log = logging.getLogger("tdigest")

_PAT_CACHE: dict[str, re.Pattern] = {}


def keyword_hit(text_lower: str, phrase: str) -> bool:
    """Word-boundary, case-insensitive match of a keyword/phrase."""
    phrase = phrase.strip().lower()
    if not phrase:
        return False
    pat = _PAT_CACHE.get(phrase)
    if pat is None:
        pat = re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)")
        _PAT_CACHE[phrase] = pat
    return pat.search(text_lower) is not None


def cosine(a: list[float], b: list[float]) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class Embedder:
    """Semantic scorer. provider: off | openai | local.

    - off:    no AI (keywords only)
    - openai: any OpenAI-compatible /embeddings endpoint (uses stdlib HTTP, no SDK)
    - local:  sentence-transformers on your own machine (free, private)
    """

    def __init__(self, provider: str, api_key: str | None = None,
                 base_url: str = "https://api.openai.com/v1", model: str | None = None):
        self.provider = provider
        self.model_name = model
        self._st = None
        if provider == "openai":
            self.model_name = model or "text-embedding-3-small"
            self.api_key = api_key
            self.base_url = base_url
            if not self.api_key:
                raise ValueError("AI_PROVIDER=openai but OPENAI_API_KEY is empty")
        elif provider == "local":
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ValueError(
                    "AI_PROVIDER=local requires: pip install sentence-transformers"
                ) from e
            self.model_name = model or "sentence-transformers/all-MiniLM-L6-v2"
            log.info("Loading local embedding model %s …", self.model_name)
            self._st = SentenceTransformer(self.model_name)
        elif provider != "off":
            raise ValueError(f"Unknown AI_PROVIDER {provider!r} (use off | openai | local)")

    def available(self) -> bool:
        return self.provider != "off"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.provider == "local":
            return [list(map(float, v)) for v in self._st.encode(texts)]
        req = urllib.request.Request(
            self.base_url + "/embeddings",
            data=json.dumps({"model": self.model_name, "input": texts}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read().decode())
        data = sorted(payload["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]


class Matcher:
    """Decides which topics a message belongs to.

    Rule order per topic:
      1. any `exclude` keyword hit          -> topic rejected
      2. any `keywords` hit                 -> match at keyword_score (default 1.0)
      3. embedding cosine >= threshold      -> match (score = similarity, tagged "ai")
    """

    def __init__(self, topics, keyword_score: float = 1.0, embedder: Embedder | None = None):
        self.topics = list(topics)
        self.keyword_score = float(keyword_score)
        self.embedder = embedder
        self._topic_vecs: list[list[float]] | None = None
        if self.embedder and self.embedder.available():
            descs = [(t.description or t.name) for t in self.topics]
            self._topic_vecs = self.embedder.embed(descs)
            log.info("Embedded %d topic descriptions", len(descs))

    def match(self, text: str) -> list[tuple]:
        """Return [(topic, score, via)] sorted by score desc; empty if no match."""
        tl = text.lower()
        results: dict[int, tuple] = {}
        eligible: list[int] = []
        for i, topic in enumerate(self.topics):
            if any(keyword_hit(tl, kw) for kw in topic.exclude):
                continue
            eligible.append(i)
            if any(keyword_hit(tl, kw) for kw in topic.keywords):
                results[i] = (topic, self.keyword_score, "keyword")
        # keywords already give maximal certainty -> skip the AI pass entirely
        if results and self.keyword_score >= 1.0:
            return sorted(results.values(), key=lambda r: -r[1])
        if self._topic_vecs is not None and eligible:
            vec = self.embedder.embed([text[:2000]])[0]
            for i in eligible:
                topic = self.topics[i]
                s = cosine(vec, self._topic_vecs[i])
                if s >= topic.threshold and (i not in results or s > results[i][1]):
                    results[i] = (topic, float(s), "ai")
        return sorted(results.values(), key=lambda r: -r[1])


class LLMClassifier:
    """LLM-based categorization, quality filtering, and 1-sentence summarization.

    Supports Groq, OpenAI, or any OpenAI-compatible chat completions endpoint.
    Uses standard library urllib.request (zero dependencies).
    """

    def __init__(self, provider: str, api_key: str | None = None,
                 base_url: str | None = None, model: str | None = None):
        self.provider = (provider or "").strip().lower()
        self.api_key = api_key
        if self.provider == "groq":
            self.base_url = (base_url or "https://api.groq.com/openai/v1").rstrip("/")
            self.model_name = model or "qwen/qwen3.8-27b"
        elif self.provider in ("openai", "llm"):
            self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
            self.model_name = model or "gpt-4o-mini"
        else:
            self.base_url = (base_url or "https://api.groq.com/openai/v1").rstrip("/")
            self.model_name = model or "qwen/qwen3.8-27b"

    def available(self) -> bool:
        return self.provider not in ("off", "") and bool(self.api_key or "localhost" in self.base_url)

    def process_batch(self, items: list[dict], topics) -> list[dict]:
        """Process candidate items in batch.

        Each item in items: {"id": int, "text": str, "topic": str}
        Returns list of results: [{"id": 0, "category": str, "summary": str, "quality": int}]
        """
        if not items or not self.available():
            return []

        topic_descriptions = "\n".join(f"- {t.name}: {t.description or 'No description'}" for t in topics)

        system_prompt = (
            "You are an expert news editor and classifier for a Telegram digest bot.\n"
            "Given a list of posts and valid topics, perform 3 tasks for each post:\n"
            "1. Assign the SINGLE BEST matching topic from the valid topics list. If off-topic/junk/spam, set category to 'NONE'.\n"
            "2. Write a concise 1-sentence summary (max 20 words) of the core news/event.\n"
            "3. Rate quality/relevance from 1 (junk/spam) to 10 (breaking high-value news).\n\n"
            "Valid Topics:\n" + topic_descriptions + "\n\n"
            "Respond ONLY with a valid JSON object containing an 'items' list with keys: id (int), category (str), summary (str), quality (int)."
        )

        user_content = json.dumps({
            "posts": [
                {"id": i, "text": item["text"][:1200], "initial_category": item.get("topic", "")}
                for i, item in enumerate(items)
            ]
        }, ensure_ascii=False)

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tdigest/1.0",
        }

        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                res_data = json.loads(r.read().decode("utf-8"))
            raw_content = res_data["choices"][0]["message"]["content"].strip()
            if raw_content.startswith("```"):
                raw_content = re.sub(r"^```(?:json)?\n?", "", raw_content)
                raw_content = re.sub(r"\n?```$", "", raw_content)
            
            parsed = json.loads(raw_content)
            if isinstance(parsed, dict):
                return parsed.get("items") or parsed.get("posts") or []
            if isinstance(parsed, list):
                return parsed
            return []
        except Exception as e:
            log.warning("LLM batch processing failed: %s", e)
            return []

    def answer_query(self, query: str, context_posts: list[dict]) -> str:
        """Answer user's RAG question using retrieved Telegram post context."""
        if not self.available() or not context_posts:
            return "<i>No relevant posts found in your channel feed to answer this question.</i>"

        posts_str = "\n\n".join([
            f"Post #{i+1}:\n"
            f"Channel: {p['channel_title']}\n"
            f"Topic: {p['topic']}\n"
            f"Link: {p['link']}\n"
            f"Content: {p['text'][:800]}"
            for i, p in enumerate(context_posts)
        ])

        system_prompt = (
            "You are an AI assistant answering questions about recent Telegram channel updates.\n"
            "Answer the user's question accurately using ONLY the provided Telegram posts.\n"
            "Format your answer using Telegram HTML markup (<b>bold</b>, <i>italic</i>, and <a href='LINK'>CHANNEL_TITLE</a>).\n"
            "For every main point or claim, include a hyperlink <a href='LINK'>CHANNEL_TITLE</a> to the original source post.\n"
            "Keep your answer clear, informative, and concise."
        )

        user_prompt = f"User Question: {query}\n\nRetrieved Telegram Posts:\n{posts_str}"

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tdigest/1.0",
        }

        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res_data = json.loads(r.read().decode("utf-8"))
            return res_data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log.warning("LLM answer query failed: %s", e)
            return f"❌ Failed to generate AI answer: {e}"
