"""Offline smoke tests — no Telegram credentials needed.

Run:  python tests/smoke_test.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from tdigest.config import load_interests            # noqa: E402
from tdigest.dedupe import Clusters, cluster_key, normalize_url   # noqa: E402
from tdigest.digest import build_messages, compact_number, message_link, snippet  # noqa: E402
from tdigest.matching import Matcher, cosine, keyword_hit         # noqa: E402


def main() -> None:
    # 1) interests.yaml loads and has topics
    icfg, topics = load_interests(os.path.join(ROOT, "interests.yaml"))
    assert topics and all(t.name for t in topics), "no topics loaded"

    # 2) keyword matching (word boundaries!)
    assert keyword_hit("this is about ai safety", "ai")
    assert not keyword_hit("said it again and again", "ai")
    assert cosine([1.0, 0.0], [1.0, 0.0]) > 0.99
    assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9

    # 3) hybrid matcher with AI off
    m = Matcher(topics, keyword_score=icfg.get("keyword_score", 1.0), embedder=None)
    hits = m.match("OpenAI just released a new GPT model for developers")
    assert hits and hits[0][2] == "keyword", f"expected keyword hit, got {hits}"

    hits = m.match("Win a free bet at our casino giveaway!")
    assert not any("Deals" in t.name for t, _, _ in hits), "exclude list failed"

    hits = m.match("zzzz nothing interesting qqqq")
    assert hits == [], "unexpected match"

    # 4) URL normalization & cluster keys
    assert normalize_url("HTTPS://www.Example.com/path/?utm_source=x&a=1#frag") == \
        "https://example.com/path?a=1"
    k1 = cluster_key("check this https://x.com/post/1?utm_medium=tg",
                     ["https://x.com/post/1?utm_medium=tg"])
    k2 = cluster_key("same link, different caption",
                     ["https://x.com/post/1"])
    assert k1 == k2, "same URL with different captions/params must cluster together"

    # 5) compact_number tests
    assert compact_number(500) == "500"
    assert compact_number(1200) == "1.2K"
    assert compact_number(1500000) == "1.5M"

    # 6) clustering keeps best-velocity representative, counts channels
    t0 = topics[0].name
    c = Clusters()
    c.add(k1, topic=t0, score=1.0, via="keyword", channel_title="Chan A",
          link="https://t.me/c/1/5", text="GPT news " * 30, other_topics=[],
          views=1000, velocity=50.0)
    c.add(k1, topic=t0, score=0.9, via="keyword", channel_title="Chan B",
          link="https://t.me/c/2/9", text="another take", other_topics=[],
          views=15000, velocity=300.0, is_viral=True)
    cl = c.items[k1]
    assert cl["count"] == 2 and len(cl["channels"]) == 2
    assert cl["best"]["link"].endswith("/9"), "higher velocity should represent cluster"

    # 7) digest rendering with engagement metrics & virality badge
    assert message_link("chan", 123, 7) == "https://t.me/chan/7"
    assert message_link(None, 123, 7) == "https://t.me/c/123/7"
    assert len(snippet("x " * 200)) <= 111
    stats = {"channels": 2, "messages": 50, "matched": 2, "unique": 1}
    msgs = build_messages(datetime.now(), stats, [cl], topics, viral_threshold=150.0, show_metrics=True)
    assert len(msgs) == 1 and "Daily Digest" in msgs[0]
    assert "seen in 2 channels" in msgs[0]
    assert "🔥" in msgs[0]
    assert "👁 15K" in msgs[0]
    assert all(len(x) <= 4000 for x in msgs)

    # 8) chunking: many items must split into multiple <= max_chars messages
    big = []
    for i in range(300):
        key = f"txt:{i}"
        c.add(key, topic=t0, score=0.5, via="ai", channel_title=f"Channel number {i}",
              link=f"https://t.me/x/{i}", text="some long text " * 15 + str(i),
              other_topics=[])
        big.append(c.items[key])
    many = build_messages(datetime.now(), stats, big, topics, max_chars=1000)
    assert len(many) > 1 and all(len(x) <= 1000 for x in many), "chunking failed"

    print("✅ All smoke tests passed")


if __name__ == "__main__":
    main()
