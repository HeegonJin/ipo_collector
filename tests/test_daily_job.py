"""수기 상장 일정 + 일일 판단 작업 (합성 자료, 키 없이)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.tradingcal import KST  # noqa: E402
from ledger.ledger import Ledger  # noqa: E402
from ops import daily_job, schedule  # noqa: E402
from test_strategies_bc import LISTING, b_market, bar, facts  # noqa: E402

NOW = datetime(2026, 11, 16, 10, 0, tzinfo=KST)


def reg_row(name="새회사", ipo_id="I1", list_dd="", rcept="20261001", price="10000"):
    return {"corp_name": name, "ipo_id": ipo_id, "is_ipo_candidate": "True", "list_dd": list_dd, "first_rcept_dt": rcept,
            "offer_price_status": "확인", "offer_price_final": price, "offer_price_available_dt": "20261101", "offer_price_rcept": "R1"}


# ── 일정 파일 ───────────────────────────────────────────────────
def test_add_and_load_roundtrip_and_reject_duplicates(tmp_path):
    p = tmp_path / "s.csv"
    e = schedule.add(p, "20261116", "새회사", "0158s0", "10,000", now=NOW)
    assert e.stock_code == "0158S0" and e.offer_price == 10000.0
    assert schedule.load(p) == [e]
    with pytest.raises(ValueError):
        schedule.add(p, "20261116", "새회사", "0158S0", now=NOW)
    assert schedule.load(tmp_path / "none.csv") == []


@pytest.mark.parametrize("args", [("20261115", "회사", "123456"), ("20261116", "", "123456"), ("20261116", "회사", "12345"),
                                  ("20261116", "회사", "123456", "-5"), ("2026-11-16", "회사", "123456")])
def test_bad_entries_are_rejected(tmp_path, args):
    with pytest.raises(ValueError):
        schedule.add(tmp_path / "s.csv", *args, now=NOW)


def test_match_registry_prefers_latest_filing_and_skips_already_listed_other_day():
    e = schedule.Entry("20261116", "새회사", "123456", None, NOW)
    rows = [reg_row(ipo_id="old", rcept="20250101"), reg_row(ipo_id="new", rcept="20261001"), reg_row(ipo_id="x", list_dd="20250601")]
    assert schedule.match_registry(e, rows)["ipo_id"] == "new"
    assert schedule.match_registry(e, [reg_row(name="다른회사")]) is None


def test_entered_after_the_decision_time_is_not_visible():
    late = schedule.Entry("20261116", "새회사", "123456", None, datetime(2026, 11, 16, 16, 0, tzinfo=KST))
    from decide.runner import run_decision_point
    out = run_decision_point(daily_job.a0_as_of("20261116"), ["I1"], schedule.facts_for(late, "I1", reg_row()), [])
    assert out[0].action == "관망"


# ── A0 ──────────────────────────────────────────────────────────
@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "l.jsonl")


def test_a0_buys_todays_listing_and_records_unmapped_as_watch(ledger):
    entered = datetime(2026, 11, 10, tzinfo=KST)
    entries = [schedule.Entry("20261116", "새회사", "123456", None, entered),
               schedule.Entry("20261116", "모르는회사", "654321", None, entered),
               schedule.Entry("20261117", "내일회사", "111111", None, entered)]
    wall = datetime(2026, 11, 16, 15, 21, tzinfo=KST)
    rep = daily_job.decide_a0("20261116", entries, [reg_row()], ledger, wall)
    by_name = {r["name"]: r for r in rep}
    assert by_name["새회사"]["action"] == "매수" and "내일회사" not in by_name
    assert by_name["모르는회사"]["action"] == "관망"
    rows = ledger.rows()
    assert {r["action"] for r in rows} == {"매수", "관망"} and all(r["valid"] for r in rows)
    assert ledger.verify() == []


def test_a0_late_recording_is_flagged_invalid(ledger):
    entries = [schedule.Entry("20261116", "새회사", "123456", None, datetime(2026, 11, 10, tzinfo=KST))]
    rep = daily_job.decide_a0("20261116", entries, [reg_row()], ledger, datetime(2026, 11, 16, 16, 30, tzinfo=KST))
    assert rep[0]["late"] is True and ledger.rows()[0]["valid"] is False


# ── B·C ─────────────────────────────────────────────────────────
def next_weekday(d):
    t = datetime.strptime(d, "%Y%m%d").date() + timedelta(days=1)
    while t.weekday() >= 5:
        t += timedelta(days=1)
    return t.strftime("%Y%m%d")


def swing_setup():
    ds, idx = b_market(60)
    stock = [bar(d, 9000) for d in ds]
    universe = [{"ipo_id": "I1", "list_dd": LISTING, "stock_code": "ABC", "corp_name": "실패공모"}]
    return next_weekday(ds[-1]), universe, facts(demand=120), stock + idx


def test_swing_records_b_once_and_never_twice(ledger):
    day, universe, fs, bars = swing_setup()
    wall = daily_job.swing_as_of(day)
    rep = daily_job.decide_swing(day, universe, fs, bars, ledger, wall)
    assert [(r["strategy"], r["recorded"]) for r in rep] == [("B_v1", True)]
    row = ledger.rows()[0]
    assert (row["strategy"], row["entry_rule"], row["exit_rule"], row["valid"]) == ("B_v1", "next_open", "B_v1", True)
    again = daily_job.decide_swing(day, universe, fs, bars, ledger, wall)
    assert again[0]["recorded"] is False and len(ledger.rows()) == 1


def test_swing_skips_listings_not_before_today(ledger):
    day, universe, fs, bars = swing_setup()
    universe[0]["list_dd"] = day
    assert daily_job.decide_swing(day, universe, fs, bars, ledger, daily_job.swing_as_of(day)) == []


def test_swing_refuses_stale_krx_data(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_job.config, "RAW", tmp_path)
    with pytest.raises(SystemExit):
        daily_job.run_swing("20261116")


def test_previous_weekday_skips_weekend():
    assert daily_job.previous_weekday("20261116") == "20261113" and daily_job.previous_weekday("20261117") == "20261116"
