import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ids import is_temp_ipo_id, make_ipo_id, make_temp_ipo_id, short_code  # noqa: E402
from core.schema import Fact, Phase, SourceType, Status  # noqa: E402

KST = timezone(timedelta(hours=9))
T = datetime(2026, 10, 20, 15, 20, tzinfo=KST)


def _fact(**kw):
    base = dict(ipo_id="00123456_20261001000123", var="offer_price", status=Status.CONFIRMED,
                available_at=T, information_phase=Phase.PRE_LISTING,
                source_type=SourceType.DART, source_id="20261001000123", value_num=10000.0)
    base.update(kw)
    return Fact(**base)


def test_confirmed_fact_needs_value():
    with pytest.raises(ValueError):
        _fact(value_num=None)


def test_missing_fact_must_not_carry_zero():
    with pytest.raises(ValueError):
        _fact(status=Status.UNVERIFIED, value_num=0.0)
    assert _fact(status=Status.UNVERIFIED, value_num=None).value_num is None


def test_available_at_requires_timezone():
    with pytest.raises(ValueError):
        _fact(available_at=datetime(2026, 10, 20, 15, 20))


def test_ipo_id_format():
    assert make_ipo_id("00123456", "20261001000123") == "00123456_20261001000123"
    with pytest.raises(ValueError):
        make_ipo_id("123", "20261001000123")


def test_short_code_keeps_letters_as_string():
    assert short_code("KR70158S0004") == "0158S0"
    assert short_code("0158S0") == "0158S0"
    tid = make_temp_ipo_id("KR70158S0004", "20261020")
    assert tid == "K:0158S0_20261020" and is_temp_ipo_id(tid)
