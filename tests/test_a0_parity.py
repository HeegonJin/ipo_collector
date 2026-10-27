"""새 PIT 틀(run_decision_point → settle)의 A0 결과가 기존 build_sample/report 결과와 종목별로 같은지 대조."""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_sample  # noqa: E402
import config  # noqa: E402
import report  # noqa: E402
import test_logic  # noqa: E402
from core.schema import Fact, Phase, SourceType, Status  # noqa: E402
from core.tradingcal import KST, dart_available_at  # noqa: E402
from decide.runner import run_decision_point  # noqa: E402
from evaluate.backtest import run_a0  # noqa: E402
from store.bars import bars_from_krx_days, index_bars_from_krx_days  # noqa: E402

END = "20230106"


@pytest.fixture
def world(monkeypatch):
    for name in ("RAW", "MART", "META", "ROOT", "BUFFER_START", "SAMPLE_START"):
        monkeypatch.setattr(config, name, getattr(config, name))
    test_logic.setup(Path(tempfile.mkdtemp()))
    old_rows = build_sample.build(END, tag="parity")
    ksq = build_sample.load_days("ksq_daily", config.BUFFER_START, END)
    idx = build_sample.load_days("kosdaq_idx", config.BUFFER_START, END)
    bars = bars_from_krx_days(ksq) + index_bars_from_krx_days(idx)
    costs = {"commission_per_side": config.COMMISSION_PER_SIDE, "slippage_per_side": config.SLIPPAGE_PER_SIDE,
             "kosdaq_sell_tax": dict(config.KOSDAQ_SELL_TAX)}
    eligible = [r for r in old_rows if not r["excluded"]]

    def mk(r, var, **kw):
        prev = datetime.strptime(r["list_date"], "%Y%m%d") - timedelta(days=1)
        return Fact(ipo_id=r["code"], var=var, status=Status.CONFIRMED,
                    available_at=dart_available_at(prev.strftime("%Y%m%d")), information_phase=Phase.PRE_LISTING,
                    source_type=SourceType.DART, source_id="fake", **kw)

    facts = []
    for r in eligible:
        facts += [mk(r, "listing_date", value_text=r["list_date"]), mk(r, "short_code", value_text=r["short_code"]),
                  mk(r, "offer_price", value_num=r["offer_price_est"])]
    return eligible, facts, bars, costs


def test_a0_matches_old_pipeline_per_ipo(world):
    eligible, facts, bars, costs = world
    results = run_a0([r["code"] for r in eligible], facts, bars, costs)
    assert {d.ipo_id for d, _ in results} == {r["code"] for r in eligible}
    old = {r["code"]: r for r in eligible}
    for d, s in results:
        o = old[d.ipo_id]
        assert s.entry_px == o["d0_close"] and s.exit_px == o["d1_open"]
        assert s.gross_ret == pytest.approx(o["gross_ret"], abs=1e-9)
        assert s.net_ret == pytest.approx(o["net_ret"], abs=1e-9)
        assert s.buy_at_limit_up == o["buy_at_limit_up"]
        assert s.bench_ret == pytest.approx(o["kosdaq_overnight"], abs=1e-9)


def test_settles_without_index_bars_using_the_stock_calendar(world):
    eligible, facts, bars, costs = world
    no_index = [b for b in bars if b["short_code"] != "KOSDAQ"]
    with_idx = {d.ipo_id: s for d, s in run_a0([r["code"] for r in eligible], facts, bars, costs)}
    without = {d.ipo_id: s for d, s in run_a0([r["code"] for r in eligible], facts, no_index, costs)}
    for ipo_id, s in without.items():
        assert s.net_ret == pytest.approx(with_idx[ipo_id].net_ret, abs=1e-12)  # D1 을 지수 없이도 찾는다
        assert s.bench_ret is None                                               # 기준선은 계산 불가


def test_summary_mean_matches_report(world):
    eligible, facts, bars, costs = world
    new = report.summarize([s.net_ret for _, s in run_a0([r["code"] for r in eligible], facts, bars, costs)])
    old = report.summarize([r["net_ret"] for r in eligible])
    assert new["mean"] == pytest.approx(old["mean"], abs=1e-9) and new["n"] == old["n"]


def test_no_decision_before_1520_or_on_other_days(world):
    eligible, facts, bars, costs = world
    r = eligible[0]
    d0 = datetime.strptime(r["list_date"], "%Y%m%d")
    early = run_decision_point(d0.replace(hour=15, minute=19, tzinfo=KST), [r["code"]], facts, bars)
    other = run_decision_point((d0 + timedelta(days=1)).replace(hour=15, minute=20, tzinfo=KST), [r["code"]], facts, bars)
    before_fact = run_decision_point((d0 - timedelta(days=3)).replace(hour=15, minute=20, tzinfo=KST), [r["code"]], facts, bars)
    assert early[0].action == other[0].action == before_fact[0].action == "관망"


def test_missing_tax_year_raises_instead_of_none(world):
    eligible, facts, bars, costs = world
    costs = {**costs, "kosdaq_sell_tax": {2022: 0.0023}}
    with pytest.raises(ValueError, match="2023"):
        run_a0([r["code"] for r in eligible], facts, bars, costs)


def test_unknown_offer_price_gives_unknown_limit_up_not_false(world):
    eligible, facts, bars, costs = world
    facts = [f for f in facts if f.var != "offer_price"]
    results = run_a0([r["code"] for r in eligible], facts, bars, costs)
    assert all(s.buy_at_limit_up is None for _, s in results)
    assert all("offer_price 미확인" in d.reasons for d, _ in results)
