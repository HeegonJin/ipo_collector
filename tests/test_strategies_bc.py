"""전략 B·C 신호와 가변 청산 모의 (합성 시세, 키 없이)."""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import settings  # noqa: E402
from core.pit import PitReader  # noqa: E402
from core.schema import Fact, Phase, SourceType, Status  # noqa: E402
from core.tradingcal import KST, krx_daily_available_at  # noqa: E402
from evaluate.swing import as_of_for, simulate_exit  # noqa: E402
from strategies import b, c  # noqa: E402
from strategies.common import add_months  # noqa: E402

LISTING = "20250102"


def days(n, start=date(2025, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def bar(d, close, volume=1000, shares=1_000_000, open_=None):
    at = krx_daily_available_at(datetime.strptime(d, "%Y%m%d").date())
    return {"date": d, "short_code": "ABC", "open": open_ or close, "close": close, "high": close, "low": close,
            "volume": volume, "shares": shares, "available_at": at}


def idx_bar(d, close):
    return {**bar(d, close), "short_code": "KOSDAQ"}


def fact(var, num=None, text=None, status=Status.CONFIRMED):
    return Fact("I1", var, status, datetime(2024, 12, 20, tzinfo=KST), Phase.PRE_LISTING, SourceType.DART, "x",
                value_num=num if status is Status.CONFIRMED else None, value_text=text if status is Status.CONFIRMED else None)


def facts(demand=100.0, demand_status=Status.CONFIRMED, **extra):
    base = [fact("short_code", text="ABC"), fact("listing_date", text=LISTING), fact("offer_price", num=10000.0),
            fact("demand_ratio", num=demand, status=demand_status)]
    return base + [fact(k, num=v) for k, v in extra.items()]


def reader(fs, stock_bars, index_bars, last):
    return PitReader(fs, stock_bars + index_bars, as_of_for(last))


# ── B ──────────────────────────────────────────────────────────
def b_params(**over):
    p = settings.load_strategy("B_v1")
    p["entry"].update(over)
    return p


def b_market(n_total, low_at=30, rebound=1.10):
    """코스닥: 1000 에서 시작해 low_at 번째에 900 으로 떨어졌다가 rebound 배로 회복."""
    ds = days(n_total)
    vals = [1000 - (100 * i / low_at) if i <= low_at else 900 * (1 + (rebound - 1) * min(1, (i - low_at) / 10)) for i in range(n_total)]
    return ds, [idx_bar(d, v) for d, v in zip(ds, vals)]


def test_b_buys_a_failed_ipo_when_the_market_rebounds():
    ds, idx = b_market(60)
    stock = [bar(d, 9000) for d in ds]                            # 공모가(10000) 아래
    sig = b.evaluate(reader(facts(demand=120), stock, idx, ds[-1]), "I1", b_params())
    assert sig.action == "매수" and "경쟁률 120배" in sig.reasons[0]


def test_b_passes_when_demand_was_strong_or_unconfirmed_or_price_above_offer():
    ds, idx = b_market(60)
    low = [bar(d, 9000) for d in ds]
    assert b.evaluate(reader(facts(demand=900), low, idx, ds[-1]), "I1", b_params()).action == "관망"
    unk = b.evaluate(reader(facts(demand=None, demand_status=Status.UNVERIFIED), low, idx, ds[-1]), "I1", b_params())
    assert unk.action == "관망" and "미확인" in unk.reasons[0]                       # 모르면 0 으로 보지 않는다
    high = [bar(d, 12000) for d in ds]
    assert b.evaluate(reader(facts(demand=120), high, idx, ds[-1]), "I1", b_params()).action == "관망"


def test_b_needs_the_market_to_have_rebounded_and_a_listing_age_in_range():
    ds, idx = b_market(60, rebound=1.02)                                           # +2% 만 반등
    stock = [bar(d, 9000) for d in ds]
    assert b.evaluate(reader(facts(), stock, idx, ds[-1]), "I1", b_params()).action == "관망"
    ds2, idx2 = b_market(15)
    assert "범위 밖" in b.evaluate(reader(facts(), [bar(d, 9000) for d in ds2], idx2, ds2[-1]), "I1", b_params()).reasons[0]


def test_b_does_not_see_bars_that_are_not_public_yet():
    ds, idx = b_market(60)
    stock = [bar(d, 9000) for d in ds]
    early = PitReader(facts(), stock + idx, as_of_for(ds[-2]))                    # 마지막 날 일봉은 아직 비공개
    assert early.bars("ABC")[-1]["date"] == ds[-2]


# ── C ──────────────────────────────────────────────────────────
def c_series(spike=True, stable=True, crash=False):
    """상장 후 1개월 해제일 전 평온 → 해제 5일(거래량 급증 여부, 안정 여부, 붕괴 여부) 하는 합성 시세. 관찰 마지막 날까지만 돌려준다."""
    ds = days(40)
    unlock = next(d for d in ds if d >= add_months(LISTING, 1))
    iu = ds.index(unlock)
    out = []
    for i, d in enumerate(ds):
        vol, px = 1000, 10000.0
        if iu <= i < iu + 5:
            vol = 5000 if spike and i == iu + 1 else 1000
            px = (7000 if crash else 10000) + (0 if stable else (600 if i % 2 else -600))
        out.append(bar(d, px, volume=vol))
    last = ds[iu + 4]
    return [b_ for b_ in out if b_["date"] <= last], last


def c_params():
    return settings.load_strategy("C_v1")


def c_facts(qty=100_000.0):
    return facts(commit_1m_qty=qty)


def test_c_buys_after_a_volume_spike_and_a_stable_close():
    stock, last = c_series()
    sig = c.evaluate(reader(c_facts(), stock, [], last), "I1", c_params())             # 해제 물량 100000/1000000 = 10%
    assert sig.action == "매수" and sig.reasons[0] == "해제 1개월"


def test_c_passes_without_a_spike_or_when_unstable_or_collapsing():
    for kw in ({"spike": False}, {"stable": False}, {"crash": True}):
        stock, last = c_series(**kw)
        assert c.evaluate(reader(c_facts(), stock, [], last), "I1", c_params()).action == "관망", kw


def test_c_ignores_small_unlocks_and_missing_commit_quantities():
    stock, last = c_series()
    assert c.evaluate(reader(c_facts(qty=10_000.0), stock, [], last), "I1", c_params()).action == "관망"      # 1% < 5%
    none = c.evaluate(reader(facts(), stock, [], last), "I1", c_params())
    assert none.action == "관망" and any("미확인" in r for r in none.reasons)


def test_c_only_fires_on_the_day_the_window_ends():
    stock, last = c_series()
    assert c.evaluate(reader(c_facts(), stock[:-1], [], stock[-2]["date"]), "I1", c_params()).action == "관망"


def test_add_months_clamps_to_month_end():
    assert add_months("20250131", 1) == "20250228" and add_months("20250102", 6) == "20250702" and add_months("20241231", 3) == "20250331"


# ── 청산 모의 ──────────────────────────────────────────────────
CFG = {"hold_days": 5, "stop_loss_pct": 10.0, "take_profit_pct": 20.0}


def path(opens_closes):
    ds = days(len(opens_closes) + 3)
    mine = {d: {"open": o, "close": cl} for d, (o, cl) in zip(ds, opens_closes)}
    return mine, ds


def test_exit_after_the_holding_period_at_that_days_open():
    mine, cal = path([(100, 100)] * 8)
    r = simulate_exit(mine, cal, cal[0], 100.0, CFG)
    assert (r["reason"], r["exit_date"], r["kind"]) == ("기간", cal[5], "정상")


def test_stop_loss_sells_at_the_next_open_after_a_bad_close():
    mine, cal = path([(100, 100), (100, 89), (85, 85), (80, 80), (80, 80), (80, 80), (80, 80), (80, 80)])
    r = simulate_exit(mine, cal, cal[0], 100.0, CFG)
    assert (r["reason"], r["exit_date"], r["exit_px"]) == ("손절", cal[2], 85)           # 종가 89 → 다음 날 시가 85


def test_take_profit_sells_at_the_next_open():
    mine, cal = path([(100, 100), (100, 121), (130, 125), (125, 125), (125, 125), (125, 125), (125, 125), (125, 125)])
    r = simulate_exit(mine, cal, cal[0], 100.0, CFG)
    assert (r["reason"], r["exit_px"]) == ("익절", 130)


def test_unreached_exit_day_is_pending_and_a_vanished_stock_is_a_delisting():
    mine, cal = path([(100, 100)] * 3)
    assert simulate_exit(mine, cal[:3], cal[0], 100.0, CFG)["kind"] == "미도래"            # 달력이 청산일 전에 끝남
    gone = {d: v for d, v in list(mine.items())[:2]}                                  # 2일째까지만 거래, 달력은 계속
    r = simulate_exit(gone, days(10), days(10)[0], 100.0, CFG)
    assert r["kind"] == "폐지" and r["exit_px"] == 100


def test_strategy_config_loader_rejects_missing_parts(tmp_path):
    (tmp_path / "strategy_X_v1.yaml").write_text("entry: {a: 1}\nexit: {hold_days: 3}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        settings.load_strategy("X_v1", tmp_path)
    with pytest.raises(ValueError):
        settings.load_strategy("../evil")
