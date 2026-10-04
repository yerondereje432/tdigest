"""SQLite state: per-channel read cursors + memory of already-digested items."""
from __future__ import annotations

import sqlite3
import time


class State:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL;")
        self.db.execute("PRAGMA synchronous=NORMAL;")
        self.db.execute("PRAGMA busy_timeout=5000;")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS cursors (
                channel_id  INTEGER PRIMARY KEY,
                last_msg_id INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS seen (
                key TEXT PRIMARY KEY,
                ts  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS muted (
                channel_id INTEGER PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                channel_title TEXT,
                topic TEXT,
                text TEXT,
                snippet TEXT,
                link TEXT,
                views INTEGER DEFAULT 0,
                forwards INTEGER DEFAULT 0,
                reactions INTEGER DEFAULT 0,
                ts REAL NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
                key UNINDEXED,
                channel_title,
                topic,
                text,
                snippet UNINDEXED,
                link UNINDEXED,
                views UNINDEXED,
                forwards UNINDEXED,
                reactions UNINDEXED,
                ts UNINDEXED
            );
            """
        )
        self.db.commit()

    # ---- per-channel read cursor (message ids grow monotonically per channel) ----
    def get_cursor(self, channel_id: int) -> int:
        row = self.db.execute(
            "SELECT last_msg_id FROM cursors WHERE channel_id=?", (channel_id,)
        ).fetchone()
        return int(row[0]) if row else 0

    def set_cursor(self, channel_id: int, msg_id: int) -> None:
        if msg_id <= 0:
            return
        self.db.execute(
            "INSERT INTO cursors(channel_id, last_msg_id) VALUES(?, ?) "
            "ON CONFLICT(channel_id) DO UPDATE SET last_msg_id=excluded.last_msg_id",
            (channel_id, msg_id),
        )
        self.db.commit()

    # ---- dedup & post memory (across runs) ----
    def is_seen(self, key: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM seen WHERE key=?", (key,)
        ).fetchone() is not None

    def mark_seen(self, keys) -> None:
        now = time.time()
        self.db.executemany(
            "INSERT OR IGNORE INTO seen(key, ts) VALUES(?, ?)", [(k, now) for k in keys]
        )
        self.db.commit()

    def save_posts(self, clusters: list[dict]) -> None:
        now = time.time()
        rows = []
        fts_rows = []
        for c in clusters:
            b = c["best"]
            row = (
                c["key"],
                b["channel_title"],
                b["topic"],
                b.get("text_raw") or b.get("snippet", ""),
                b["snippet"],
                b["link"],
                b.get("views", 0),
                b.get("forwards", 0),
                b.get("reactions", 0),
                now
            )
            rows.append(row)
            fts_rows.append(row)

        self.db.executemany(
            """INSERT INTO posts(key, channel_title, topic, text, snippet, link, views, forwards, reactions, ts)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
               views=excluded.views, forwards=excluded.forwards, reactions=excluded.reactions, ts=excluded.ts""",
            rows
        )
        try:
            self.db.executemany(
                """INSERT OR REPLACE INTO posts_fts(key, channel_title, topic, text, snippet, link, views, forwards, reactions, ts)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                fts_rows
            )
        except Exception:
            pass
        self.db.commit()

    def search_posts(self, query: str, limit: int = 15) -> list[dict]:
        """Search posts by FTS5 BM25 relevance ranking or fallback to keyword matching."""
        words = [w.strip().replace('"', '') for w in query.split() if len(w.strip()) > 1]
        results = []
        
        # 1. Try SQLite FTS5 Match with BM25 ranking
        if words:
            fts_query = " OR ".join(f'"{w}"' for w in words)
            try:
                cursor = self.db.execute(
                    """SELECT channel_title, topic, text, snippet, link, views, forwards, reactions, ts, bm25(posts_fts) as rank
                       FROM posts_fts
                       WHERE posts_fts MATCH ?
                       ORDER BY rank ASC, ts DESC
                       LIMIT ?""",
                    (fts_query, limit)
                )
                for row in cursor.fetchall():
                    results.append({
                        "channel_title": row[0],
                        "topic": row[1],
                        "text": row[2],
                        "snippet": row[3],
                        "link": row[4],
                        "views": row[5],
                        "forwards": row[6],
                        "reactions": row[7],
                        "ts": row[8],
                    })
                if results:
                    return results
            except Exception:
                pass

        # 2. Fallback: LIKE %word% search on posts table
        if words:
            where_clauses = " OR ".join(["LOWER(text) LIKE ? OR LOWER(channel_title) LIKE ? OR LOWER(topic) LIKE ?" for _ in words])
            params = []
            for w in words:
                pattern = f"%{w.lower()}%"
                params.extend([pattern, pattern, pattern])
            params.append(limit)
            cursor = self.db.execute(
                f"SELECT channel_title, topic, text, snippet, link, views, forwards, reactions, ts FROM posts WHERE {where_clauses} ORDER BY ts DESC LIMIT ?",
                params
            )
        else:
            cursor = self.db.execute(
                "SELECT channel_title, topic, text, snippet, link, views, forwards, reactions, ts FROM posts ORDER BY ts DESC LIMIT ?",
                (limit,)
            )

        for row in cursor.fetchall():
            results.append({
                "channel_title": row[0],
                "topic": row[1],
                "text": row[2],
                "snippet": row[3],
                "link": row[4],
                "views": row[5],
                "forwards": row[6],
                "reactions": row[7],
                "ts": row[8],
            })
        return results

    def prune(self, days: int = 30) -> None:
        cutoff = time.time() - days * 86400
        self.db.execute("DELETE FROM seen WHERE ts < ?", (cutoff,))
        self.db.execute("DELETE FROM posts WHERE ts < ?", (cutoff,))
        try:
            self.db.execute("DELETE FROM posts_fts WHERE ts < ?", (cutoff,))
        except Exception:
            pass
        self.db.commit()

    # ---- channel muting ----
    def mute_channel(self, channel_id: int) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO muted(channel_id) VALUES(?)", (channel_id,)
        )
        self.db.commit()

    def unmute_channel(self, channel_id: int) -> None:
        self.db.execute("DELETE FROM muted WHERE channel_id=?", (channel_id,))
        self.db.commit()

    def is_muted(self, channel_id: int) -> bool:
        return self.db.execute(
            "SELECT 1 FROM muted WHERE channel_id=?", (channel_id,)
        ).fetchone() is not None

    def get_muted(self) -> set[int]:
        return {row[0] for row in self.db.execute("SELECT channel_id FROM muted")}

    def close(self) -> None:
        self.db.close()
