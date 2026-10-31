"""전략 백테스트 API: 규칙 숫자 덮어쓰기 검증, 쏠림 점검, 합성 자료로 B 규칙을 as_of 별로 돌려 보기."""
import pytest

from core import settings
from lab import strategy_api as sa


def test_overrides_are_validated_and_applied_to_a_copy():
    base = settings.load_strategy("B_v1")
    p = sa.apply_overrides("B_v1", base, {"entry.max_demand_ratio": 500, "exit.hold_days": 20})
    assert p["entry"]["max_demand_ratio"] == 500 and p["exit"]["hold_days"] == 20 and isinstance(p["exit"]["hold_days"], int)
    assert base["exit"]["hold_days"] == 40                                   # 원본 불변
    assert sa.changed("B_v1", base, p) == {"entry.max_demand_ratio": 500, "exit.hold_days": 20}
    for bad in ({"entry.nope": 1}, {"exit.hold_days": 1000}, {"exit.hold_days": 12.5}, {"entry.min_days_since_listing": 60, "entry.max_days_since_listing": 60.0 - 10}):
        with pytest.raises(ValueError):
            sa.apply_overrides("B_v1", base, bad)


def test_concentration_flags_when_the_top_two_carry_the_mean():
    rets = [0.5, 0.4] + [-0.02] * 30
    assert sa.concentration(rets)["verdict"] == "쏠림 의심"
    assert sa.concentration([0.02] * 32)["verdict"] == "분산"
    assert sa.concentration([0.1, 0.2])["verdict"] == "판단 불가"


def test_unknown_strategy_is_rejected():
    lab = sa.StrategyLab([], [], None, {}, {}, None, {"min_n": 30, "trials_warn_at": 20}, "20230101", "20261030")
    with pytest.raises(ValueError):
        lab.run("Z9")


def test_server_routes_include_the_strategy_backtest():
    import inspect
    from lab import server
    src = inspect.getsource(server.make_server)
    for route in ("/api/strategies", "/api/strategy/run", "/api/strategy/card", "/api/ipos", "/api/basic_stats"):
        assert route in src
