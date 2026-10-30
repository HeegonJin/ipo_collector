"""모의 운영 장부 흐름: 판단을 기록 → 청산일이 지나면 정산을 추가. 장부(ledger)와 정산(settle)을 잇는다."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.tradingcal import KST  # noqa: E402
from decide.runner import Decision  # noqa: E402
from evaluate.outcomes import BarIndex  # noqa: E402
from ledger.ledger import Ledger  # noqa: E402
from ops.paper_ledger import decision_from_row, record_decisions, record_unmapped, settle_due  # noqa: E402
from store.bars import CALENDAR_CODE  # noqa: E402

COSTS = {"commission_per_side": 0.00015, "slippage_per_side": 0.002, "kosdaq_sell_tax": {2026: 0.002}}
AS_OF = datetime(2026, 10, 20, 15, 20, tzinfo=KST)
AT = datetime(2026, 10, 1, tzinfo=KST)
SETTLED_AT = datetime(2026, 10, 22, 9, 0, tzinfo=KST)


def decision(ipo_id="I1", code="ABC", action="매수"):
    return Decision(ipo_id, "A0", AS_OF, action, "D0_close", "D1_open", ("조건 없는 기준선",), code, "20261020", 10000.0)


def bar(d, code, o, c):
    return {"date": d, "short_code": code, "open": o, "close": c, "available_at": AT}


def index(days, *stock_bars):
    return BarIndex([bar(d, CALENDAR_CODE, None, None) for d in days] + list(stock_bars))


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.jsonl")


def test_only_buy_decisions_are_recorded_and_recording_twice_keeps_one_row(ledger):
    ids = record_decisions(ledger, [decision("I1"), decision("I2", action="관망")], AS_OF + timedelta(seconds=30))
    assert len(ids) == 1 and len(ledger.rows()) == 1
    assert record_decisions(ledger, [decision("I1")], AS_OF + timedelta(minutes=1)) == ids
    assert len(ledger.rows()) == 1 and ledger.verify() == []


def test_decision_survives_a_round_trip_through_the_ledger(ledger):
    d = decision()
    record_decisions(ledger, [d], AS_OF)
    assert decision_from_row(ledger.rows()[0]) == d


def test_due_decisions_are_settled_once(ledger):
    record_decisions(ledger, [decision()], AS_OF)
    idx = index(["20261020", "20261021"], bar("20261020", "ABC", 9000, 10000), bar("20261021", "ABC", 11000, 11500))
    assert settle_due(ledger, idx, COSTS, SETTLED_AT) == 1
    rows = ledger.rows()
    assert [r["type"] for r in rows] == ["decision", "settlement"] and rows[1]["exit_kind"] == "정상"
    assert rows[1]["net_ret"] == pytest.approx(11000 * (1 - 0.00015 - 0.002 - 0.002) / (10000 * (1 + 0.00015 + 0.002)) - 1)
    assert settle_due(ledger, idx, COSTS, SETTLED_AT) == 0 and len(ledger.rows()) == 2 and ledger.verify() == []


def test_exit_day_not_yet_arrived_is_not_settled_until_the_data_exists(ledger):
    record_decisions(ledger, [decision()], AS_OF)
    today_only = index(["20261020"], bar("20261020", "ABC", 9000, 10000))
    assert settle_due(ledger, today_only, COSTS, SETTLED_AT) == 0 and len(ledger.rows()) == 1
    later = index(["20261020", "20261021"], bar("20261020", "ABC", 9000, 10000), bar("20261021", "ABC", 11000, 11500))
    assert settle_due(ledger, later, COSTS, SETTLED_AT) == 1


def test_a_vanished_stock_is_settled_as_a_delisting_with_no_net_return(ledger):
    record_decisions(ledger, [decision()], AS_OF)
    idx = index(["20261020", "20261021", "20261022"], bar("20261020", "ABC", 9000, 10000))
    assert settle_due(ledger, idx, COSTS, SETTLED_AT) == 1
    row = ledger.rows()[1]
    assert row["exit_kind"] == "폐지" and row["net_ret"] is None and row["net_ret_wipeout"] == -1.0


def test_decisions_recorded_too_late_are_invalid_and_never_settled(ledger):
    record_decisions(ledger, [decision()], AS_OF + timedelta(minutes=6))
    assert ledger.rows()[0]["valid"] is False
    idx = index(["20261020", "20261021"], bar("20261020", "ABC", 9000, 10000), bar("20261021", "ABC", 11000, 11500))
    assert settle_due(ledger, idx, COSTS, SETTLED_AT) == 0 and len(ledger.rows()) == 1


def test_settle_from_raw_reads_prices_for_only_the_ledger_codes_and_settles_due_rows(ledger, monkeypatch, tmp_path):
    """운영 진입점: 장부의 매수 종목 시세만 원본 KRX 자료에서 읽어 청산일이 지난 건을 정산한다."""
    import config
    import test_logic
    from ops.paper_ledger import settle_from_raw
    for name in ("RAW", "MART", "META", "ROOT", "BUFFER_START", "SAMPLE_START"):
        monkeypatch.setattr(config, name, getattr(config, name))
    test_logic.setup(tmp_path / "krx")                       # 가짜 KRX: 종목 A 는 2023-01-05 상장, 다음 날 시가 7,700, 종가 6,800
    d = Decision("A_ipo", "A0", datetime(2023, 1, 5, 15, 20, tzinfo=KST), "매수", "D0_close", "D1_open", (), "A",
                 "20230105", 10000.0)
    record_decisions(ledger, [d], d.as_of)
    assert settle_from_raw(ledger, "20230105", SETTLED_AT) == 0         # 다음 거래일 자료가 아직 없다
    assert settle_from_raw(ledger, "20230106", SETTLED_AT) == 1
    row = ledger.rows()[1]
    fee, slip, tax = 0.00015, 0.002, 0.002
    assert row["type"] == "settlement" and row["exit_kind"] == "정상"
    assert row["net_ret"] == pytest.approx(7700 * (1 - fee - slip - tax) / (6800 * (1 + fee + slip)) - 1)
    assert settle_from_raw(ledger, "20230106", SETTLED_AT) == 0 and ledger.verify() == []


def test_settle_from_raw_with_an_empty_ledger_does_nothing(ledger):
    from ops.paper_ledger import settle_from_raw
    assert settle_from_raw(ledger, "20230106", SETTLED_AT) == 0


def test_unmapped_listing_is_recorded_as_a_wait_decision_under_a_temporary_id(ledger):
    unmapped = [{"code": "0053F0", "name": "티앤이코리아", "list_date": "20261029"}]
    as_of = datetime(2026, 10, 29, 15, 20, tzinfo=KST)
    ids = record_unmapped(ledger, unmapped, as_of, as_of + timedelta(seconds=10))
    row = ledger.rows()[0]
    assert len(ids) == 1 and row["ipo_id"] == "K:0053F0_20261029" and row["action"] == "관망"
    assert any("DART 미연결" in r for r in row["reasons"]) and row["short_code"] == "0053F0"
    assert record_unmapped(ledger, unmapped, as_of, as_of) == ids and len(ledger.rows()) == 1
    idx = index(["20261029", "20261030"], bar("20261029", "0053F0", 1, 2), bar("20261030", "0053F0", 2, 3))
    assert settle_due(ledger, idx, COSTS, SETTLED_AT) == 0        # 관망은 정산하지 않는다
    assert ledger.verify() == []
