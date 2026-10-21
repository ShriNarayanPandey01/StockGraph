"""Fixed-window temporal filtering (Rule 3). No live DB required."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.domain.enums import Window
from src.domain.schemas import WINDOW_DAYS, resolve_window

IST = ZoneInfo("Asia/Kolkata")


def test_window_days_locked():
    assert WINDOW_DAYS[Window.LAST_6M] == 180
    assert WINDOW_DAYS[Window.LAST_1Y] == 365
    assert set(Window) == {Window.LAST_6M, Window.LAST_1Y}


def test_resolve_window_spans():
    now = datetime(2026, 10, 16, 12, 0, tzinfo=IST)
    start_6m, end_6m = resolve_window(Window.LAST_6M, now)
    start_1y, end_1y = resolve_window(Window.LAST_1Y, now)
    assert end_6m == end_1y == int(now.timestamp())
    assert start_1y < start_6m
    # Start is IST midnight; end is now: span covers 179 / 364 full days + intra-day.
    start_6m_dt = datetime.fromtimestamp(start_6m, tz=IST)
    start_1y_dt = datetime.fromtimestamp(start_1y, tz=IST)
    assert (now.date() - start_6m_dt.date()).days == 180 - 1
    assert (now.date() - start_1y_dt.date()).days == 365 - 1


def test_resolve_window_start_is_ist_midnight():
    now = datetime(2026, 10, 16, 23, 30, tzinfo=IST)
    start_ts, _ = resolve_window(Window.LAST_6M, now)
    start = datetime.fromtimestamp(start_ts, tz=IST)
    assert (start.hour, start.minute, start.second) == (0, 0, 0)


def test_validity_overlap_predicate_logic():
    # Validity-interval overlap: valid_from <= end AND valid_to >= start
    start, end = resolve_window(Window.LAST_6M)
    node = {"valid_from_ts": start - 100, "valid_to_ts": end + 100}
    assert node["valid_from_ts"] <= end and node["valid_to_ts"] >= start
    outside = {"valid_from_ts": end + 1, "valid_to_ts": 9999999999}
    assert not (outside["valid_from_ts"] <= end)
