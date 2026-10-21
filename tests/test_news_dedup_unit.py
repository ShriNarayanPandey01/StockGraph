"""L1–L3 dedup unit contract. Offline: fake repo + fake Redis, no live DB."""

from src.config.settings import settings
from src.processors.news_dedup import (
    NewsDeduper,
    build_news_props,
    canonicalize_url,
    deterministic_news_id,
    higher_priority,
    normalize_headline,
    source_rank,
    url_seen_key,
)


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


class _FakeRepo:
    def __init__(self, text_hit=None, near_hit=None):
        self.text_hit = text_hit
        self.near_hit = near_hit
        self.links: list[tuple[str, str]] = []
        self.merged: list[dict] = []

    def find_text_dup(self, norm_headline, ticker, window_secs):
        assert window_secs == settings.dedup_window_hours * 3600 == 48 * 3600
        return self.text_hit

    def find_near_dup(self, embedding, ticker, now_ts):
        return self.near_hit

    def link_duplicate(self, dup_id, canon_id):
        self.links.append((dup_id, canon_id))
        return {}

    def merge_news_event(self, props, embedding=None):
        self.merged.append(dict(props))
        return {"id": props["id"]}


def _props(**kw):
    base = build_news_props(
        headline=kw.get("headline", "RBI holds repo rate steady"),
        primary_entity=kw.get("ticker", "RELIANCE"),
        event_date="2026-10-17",
        event_ts=1_790_000_000,
        summary=kw.get("summary", "s"),
        source=kw.get("source", "RSS"),
        source_url=kw.get("source_url", ""),
    )
    return base


def test_canonicalize_strips_tracking_params():
    url = "https://example.com/a?utm_source=x&fbclid=1&id=5#frag"
    assert canonicalize_url(url) == "https://example.com/a?id=5"
    # Paths stay case-sensitive (servers distinguish /A from /a); only the
    # trailing slash is trimmed and host/scheme lowercased.
    assert canonicalize_url("HTTPS://Example.COM/A/") == "https://example.com/A"


def test_seen_key_shape():
    key = url_seen_key("https://example.com/a")
    assert key.startswith("seen:") and len(key) == len("seen:") + 40


def test_normalize_headline_strips_source_suffix_and_punct():
    assert normalize_headline("RBI Holds Repo Rate - Moneycontrol") == "rbi holds repo rate"
    assert normalize_headline("Tata Steel Q2 Results | Economic Times") == "tata steel q2 results"
    assert normalize_headline("  Breakout!! ") == "breakout"


def test_deterministic_id_shape_matches_routing_contract():
    nid = deterministic_news_id("rbi holds repo rate", "RELIANCE", "2026-10-17")
    assert len(nid) == 40
    assert deterministic_news_id("rbi holds repo rate", "reliance", "2026-10-17") == nid


def test_source_priority_reg30_over_rss():
    assert source_rank("REG30") > source_rank("BSE") > source_rank("NSE") > source_rank("RSS")
    assert source_rank("unknown-src") == -1
    assert higher_priority("REG30", "RSS") is True
    assert higher_priority("RSS", "REG30") is False
    assert higher_priority("RSS", "RSS") is False


def test_l1_exact_url_drop():
    deduper = NewsDeduper(repo=_FakeRepo(), redis_client=_FakeRedis())
    props = _props(source_url="https://nse.in/a?utm_source=x")
    first = deduper.process(props, embedding=None, now_ts=1_790_000_000)
    assert first.action == "created"
    second = deduper.process(props, embedding=None, now_ts=1_790_000_000)
    assert second.action == "dropped_l1"


def test_l1_fails_open_without_redis():
    deduper = NewsDeduper(repo=_FakeRepo(), redis_client=None)
    out = deduper.process(_props(source_url="https://x.in/a"), embedding=None, now_ts=1)
    assert out.action == "created"


def test_l2_links_without_embedding():
    repo = _FakeRepo(text_hit=[{"id": "canon1"}])
    deduper = NewsDeduper(repo=repo, redis_client=_FakeRedis())
    out = deduper.process(_props(), embedding=None, now_ts=1_790_000_000)
    assert out.action == "duplicate_l2" and out.canonical_id == "canon1"
    assert repo.links == [(out.news_id, "canon1")]
    assert repo.merged == []  # no chunking/embedding spent on the dup


def test_l3_duplicate_links_and_upgrades_summary_on_priority():
    canon = {
        "id": "canon1",
        "embedding": [1.0, 0.0],
        "source": "RSS",
    }
    repo = _FakeRepo(near_hit=[canon, 0.99])
    deduper = NewsDeduper(repo=repo, redis_client=_FakeRedis())
    props = _props(source="REG30", summary="Official filing text")
    out = deduper.process(props, embedding=[1.0, 0.0], now_ts=1_790_000_000)
    assert out.action == "duplicate_l3" and out.canonical_id == "canon1"
    assert (props["id"], "canon1") in repo.links
    upgrades = [m for m in repo.merged if m["id"] == "canon1"]
    assert upgrades and upgrades[0]["summary"] == "Official filing text"


def test_l3_paraphrase_band_creates_new_node():
    # cosine([1,0],[1,0.5]) ~= 0.89 < 0.92 -> NOT a dup (L4 candidate instead).
    canon = {"id": "canon1", "embedding": [1.0, 0.5], "source": "RSS"}
    repo = _FakeRepo(near_hit=[canon, 0.89])
    deduper = NewsDeduper(repo=repo, redis_client=_FakeRedis())
    out = deduper.process(_props(), embedding=[1.0, 0.0], now_ts=1_790_000_000)
    assert out.action == "created"
    assert repo.links == []


def test_l3_missing_candidate_embedding_fails_open():
    repo = _FakeRepo(near_hit=[{"id": "canon1"}, 0.99])  # no embedding stored
    deduper = NewsDeduper(repo=repo, redis_client=_FakeRedis())
    out = deduper.process(_props(), embedding=[1.0, 0.0], now_ts=1_790_000_000)
    assert out.action == "created"  # never a false merge


def test_thresholds_come_from_settings():
    assert settings.dedup_cosine_threshold == 0.92
    assert settings.dedup_window_hours == 48
    assert settings.correlation_min_cosine == 0.68
    assert settings.correlation_window_days == 14
    assert settings.ontology_min_confidence == 0.65
