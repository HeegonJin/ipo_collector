"""청산 가격이 없을 때(거래정지·상장폐지)는 조용히 통계에서 빼지 않고, 사유를 구분하고 민감도 값을 함께 낸다."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.tradingcal import KST  # noqa: E402
from decide.runner import Decision  # noqa: E402
from evaluate.outcomes import BarIndex, settle  # noqa: E402
from store.bars import CALENDAR_CODE  # noqa: E402

COSTS = {"commission_per_side": 0.00015, "slippage_per_side": 0.002, "kosdaq_sell_tax": {2026: 0.002}}
DAYS = ["20261020", "20261021", "20261022", "20261023"]
AT = datetime(2026, 10, 1, tzinfo=KST)


def bar(d, code, o, c):
    return {"date": d, "short_code": code, "open": o, "close": c, "available_at": AT}


def calendar(days=DAYS):
    return [bar(d, CALENDAR_CODE, None, None) for d in days]


def decision(d0="20261020"):
    return Decision("X_ipo", "A0", AT, "매수", "D0_close", "D1_open", (), "ABC", d0, 10000.0)


def net(exit_px, c0=10000.0):
    fee, slip, tax = 0.00015, 0.002, 0.002
    return exit_px * (1 - fee - slip - tax) / (c0 * (1 + fee + slip)) - 1


def test_normal_exit_has_no_fallbacks():
    bars = calendar() + [bar("20261020", "ABC", 9000, 10000), bar("20261021", "ABC", 11000, 11500)]
    s = settle(decision(), BarIndex(bars), COSTS)
    assert s.exit_kind == "정상" and s.net_ret == pytest.approx(net(11000))
    assert s.net_ret_last_close is None and s.net_ret_wipeout is None


def test_trading_halt_exits_at_the_first_open_after_the_halt():
    bars = calendar() + [bar("20261020", "ABC", 9000, 10000), bar("20261023", "ABC", 8000, 8200)]   # 21·22일 거래 없음
    s = settle(decision(), BarIndex(bars), COSTS)
    assert s.exit_kind == "거래정지" and s.net_ret is None and s.net_ret_status == "계산 불가"
    assert s.net_ret_last_close == pytest.approx(net(8000))       # 재개 후 첫 시가로 청산
    assert s.net_ret_wipeout == -1.0


def test_disappearing_stock_is_a_delisting_exited_at_the_last_known_close():
    bars = calendar() + [bar("20261020", "ABC", 9000, 10000)]       # D0 이후 일별 데이터에서 사라짐
    s = settle(decision(), BarIndex(bars), COSTS)
    assert s.exit_kind == "폐지" and s.net_ret is None
    assert s.net_ret_last_close == pytest.approx(net(10000))        # 마지막 종가(=D0 종가)로 청산: 비용만 손실
    assert s.net_ret_wipeout == -1.0


def test_exit_day_not_yet_arrived_is_not_a_delisting():
    bars = calendar(DAYS[:1]) + [bar("20261020", "ABC", 9000, 10000)]   # D0 가 달력의 마지막 날
    s = settle(decision(), BarIndex(bars), COSTS)
    assert s.exit_kind == "미도래" and s.net_ret is None
    assert s.net_ret_last_close is None and s.net_ret_wipeout is None
