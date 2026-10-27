import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.pit import PitReader  # noqa: E402
from core.schema import Fact, Phase, SourceType, Status  # noqa: E402
from core.tradingcal import KST, dart_available_at, krx_daily_available_at  # noqa: E402

IPO = "00123456_20261001000123"
T0 = datetime(2026, 10, 1, tzinfo=KST)


def fact(var, val, at, seq=0):
    return Fact(ipo_id=IPO, var=var, status=Status.CONFIRMED, available_at=at,
                information_phase=Phase.PRE_LISTING, source_type=SourceType.DART,
                source_id="x", value_num=val, version_seq=seq)


def bar(day, close):
    d = date(2026, 10, day)
    return {"date": d.strftime("%Y%m%d"), "short_code": "0158S0", "close": close,
            "available_at": krx_daily_available_at(d)}


def test_missing_fact_is_unverified_not_zero():
    r = PitReader([], [], T0 + timedelta(days=30))
    v = r.fact(IPO, "offer_price")
    assert v.status is Status.UNVERIFIED and v.value_num is None


def test_latest_visible_version_wins():
    facts = [fact("offer_price", 10000, T0, 0), fact("offer_price", 12000, T0 + timedelta(days=5), 1)]
    assert PitReader(facts, [], T0 + timedelta(days=2)).fact(IPO, "offer_price").value_num == 10000
    assert PitReader(facts, [], T0 + timedelta(days=6)).fact(IPO, "offer_price").value_num == 12000


def test_krx_bar_available_next_business_day_morning():
    fri = date(2026, 10, 23)
    assert krx_daily_available_at(fri).date() == date(2026, 10, 26)
    assert dart_available_at("20261027").hour == 23


def test_poison_future_values_do_not_change_results():
    rnd = random.Random(7)
    base_facts = [fact("offer_price", 10000, T0), fact("float_ratio", 0.3, T0 + timedelta(days=1))]
    base_bars = [bar(d, 1000 + d) for d in (5, 6, 7, 8)]
    for _ in range(200):
        as_of = T0 + timedelta(hours=rnd.randint(0, 24 * 20))
        clean = PitReader(base_facts, base_bars, as_of)
        poison_facts = base_facts + [fact("offer_price", 9.99e99, as_of + timedelta(seconds=1), 9)]
        poison_bars = base_bars + [{**bar(9, 9.99e99), "available_at": as_of + timedelta(seconds=1)}]
        dirty = PitReader(poison_facts, poison_bars, as_of)
        assert clean.fact(IPO, "offer_price") == dirty.fact(IPO, "offer_price")
        assert clean.bars("0158S0") == dirty.bars("0158S0")


def test_naive_as_of_rejected():
    with pytest.raises(ValueError):
        PitReader([], [], datetime(2026, 10, 1))
