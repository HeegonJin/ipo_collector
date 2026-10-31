"""L6 리스크 게이트 (합성 시세, 키 없이)."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import settings  # noqa: E402
from core.pit import PitReader  # noqa: E402
from core.tradingcal import KST, krx_daily_available_at  # noqa: E402
from decide import risk  # noqa: E402
from decide.runner import Decision  # noqa: E402

AS_OF = datetime(2026, 11, 17, 8, 30, tzinfo=KST)
P = {"paper_capital_krw": 100_000_000, "weight_per_trade": 0.10, "max_weight_per_day": 0.20, "min_weight": 0.01,
     "max_participation": 0.01, "limit_up_pct": 29.0}


def bar(d, close, volume, code="ABC"):
    return {"date": d, "short_code": code, "open": close, "close": close, "volume": volume,
            "available_at": krx_daily_available_at(datetime.strptime(d, "%Y%m%d").date())}


def dec(code="ABC", entry="next_open", ipo="I1", action="매수"):
    return Decision(ipo, "B_v1", AS_OF, action, entry, "B_v1", ("신호",), code, "20260101", 10000.0)


def run(decisions, bars, used=0.0, params=P):
    return risk.apply(decisions, PitReader([], bars, AS_OF), params, used)


def test_normal_buy_gets_the_target_weight():
    out = run([dec()], [bar("20261112", 10000, 10_000_000), bar("20261113", 10000, 10_000_000)])   # 전일 거래대금 1000억
    assert out[0].action == "매수" and out[0].weight == pytest.approx(0.10)


def test_limit_up_close_blocks_the_open_entry():
    out = run([dec()], [bar("20261112", 10000, 10_000_000), bar("20261113", 13000, 10_000_000)])
    assert out[0].action == "관망" and "상한가" in out[0].reasons[-1] and out[0].weight is None


def test_thin_trading_scales_the_weight_down_or_blocks():
    scaled = run([dec()], [bar("20261112", 10000, 5_000), bar("20261113", 10000, 5_000)])           # 전일 거래대금 5천만원 → 한도 50만원 = 0.5%
    assert scaled[0].action == "관망" and "거래대금" in scaled[0].reasons[-1]                          # 0.5% < 최소 1%
    mid = run([dec()], [bar("20261112", 10000, 150_000), bar("20261113", 10000, 150_000)])          # 15억원 → 1500만원 = 비중 15% ≥ 10%
    assert mid[0].weight == pytest.approx(0.10)
    small = run([dec()], [bar("20261112", 10000, 80_000), bar("20261113", 10000, 80_000)])          # 8억원 → 800만원 = 8%
    assert small[0].action == "매수" and small[0].weight == pytest.approx(0.08) and any("비중" in r for r in small[0].reasons)


def test_daily_cap_is_shared_across_decisions_and_prior_records():
    bars = [bar(d, 10000, 10_000_000, c) for c in ("A", "B", "C") for d in ("20261112", "20261113")]
    out = run([dec("A", ipo="1"), dec("B", ipo="2"), dec("C", ipo="3")], bars)
    assert [d.action for d in out] == ["매수", "매수", "관망"] and "합산 한도" in out[2].reasons[-1]
    assert run([dec("A")], bars, used=0.15)[0].weight == pytest.approx(0.05)


def test_unknown_inputs_are_noted_not_blocked_and_non_buys_pass_through():
    a0 = run([dec(entry="D0_close")], [])
    assert a0[0].action == "매수" and "확인 불가" in a0[0].reasons[-1]
    assert run([dec(action="관망")], [])[0].action == "관망"


def test_config_loads_and_validates(tmp_path):
    assert settings.load_risk()["weight_per_trade"] == 0.10
    (tmp_path / "risk_v1.yaml").write_text("version: x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        settings.load_risk(tmp_path)
