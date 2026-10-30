"""전략 실험 앱의 평가 엔진: 사람이 고른 조건·진입·보유기간을 종목별 특징 표에 적용해 수익률을 낸다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.engine import CONDITIONS, evaluate, normalize, select  # noqa: E402

COSTS = {"commission_per_side": 0.00015, "slippage_per_side": 0.002, "kosdaq_sell_tax": {2025: 0.0015, 2026: 0.002}}


def row(i, split="train", float_pct=1.0, amount=200.0, ret=10.0, drop=-5.0, idx=0.5, c0=11000.0, opens=None, limit_up=False,
        date="20250103"):
    return {"ipo_id": f"I{i}", "name": f"종목{i}", "code": f"C{i}", "list_date": date, "split": split, "offer_price": 10000.0,
            "float_pct": float_pct, "retail_ratio": amount, "d0_ret_vs_offer": ret, "d0_drop_from_high": drop,
            "d0_index_chg": idx, "close_d0": c0,
            "open_d": opens or {0: 10500.0, 1: 11110.0, 2: 11200.0, 3: 11300.0, 4: 11400.0, 5: 11500.0, 6: 11600.0},
            "limit_up": limit_up}


def params(entry="d0_close", hold=1, **conds):
    return {"entry": entry, "hold": hold,
            "conditions": {k: {"enabled": True, "lo": v[0], "hi": v[1]} for k, v in conds.items()}}


def net(exit_px, entry_px, tax=0.0015):
    return exit_px * (1 - 0.00015 - 0.002 - tax) / (entry_px * (1 + 0.00015 + 0.002)) - 1


def test_every_condition_is_labelled_with_its_phase_and_whether_the_design_doc_has_it():
    by = {c["id"]: c for c in CONDITIONS}
    for cid in ("demand_ratio", "retail_ratio", "final_commit_pct", "float_pct"):       # 설계도 M1 변수, 상장 전 확정
        assert by[cid]["phase"] == "pre" and by[cid]["in_design"] is True
    assert "band_pos" not in by and "offer_amount_bil" not in by                    # 설계도에 없는 조건은 뺐다
    for cid in ("d0_ret_vs_offer", "d0_drop_from_high", "d0_index_chg"):
        assert by[cid]["phase"] == "d0" and by[cid]["in_design"] is True


def test_normalize_keeps_only_enabled_conditions_and_rejects_bad_input():
    p = {"entry": "d0_close", "hold": 3, "conditions": {"float_pct": {"enabled": True, "lo": 0.5, "hi": 2.0},
                                                         "d0_index_chg": {"enabled": False, "lo": -1, "hi": 1}}}
    assert normalize(p) == {"entry": "d0_close", "hold": 3, "conditions": {"float_pct": [0.5, 2.0]}}
    for bad in ({"entry": "x", "hold": 1, "conditions": {}}, {"entry": "d0_close", "hold": 2, "conditions": {}},
                params(nope=(0, 1)), params(float_pct=(2.0, 1.0)), params(float_pct=(-99.0, 1.0))):
        with pytest.raises(ValueError):
            normalize(bad)


def test_selection_keeps_rows_inside_the_range_and_counts_unknown_values_instead_of_guessing():
    rows = [row(1, float_pct=1.2), row(2, float_pct=0.4), row(3, float_pct=None)]
    kept, excluded = select(rows, normalize(params(float_pct=(1.0, 2.0))))
    assert [r["ipo_id"] for r in kept] == ["I1"]
    assert excluded == {"float_pct": 1}                              # I3 은 값을 몰라서 제외 (0 으로 채우지 않는다)


def test_d0_close_entry_exits_at_the_open_of_day_hold_after_listing():
    res = evaluate([row(1)], params(hold=1), COSTS, "train")
    assert res["stats"]["n"] == 1 and res["trades"][0]["net_ret"] == pytest.approx(net(11110.0, 11000.0))
    res3 = evaluate([row(1)], params(hold=3), COSTS, "train")
    assert res3["trades"][0]["net_ret"] == pytest.approx(net(11300.0, 11000.0))


def test_d1_open_entry_buys_the_next_open_and_exits_hold_days_later():
    res = evaluate([row(1)], params(entry="d1_open", hold=3), COSTS, "train")
    assert res["trades"][0]["net_ret"] == pytest.approx(net(11400.0, 11110.0))     # D1 시가 매수, D4 시가 매도


def test_limit_up_closes_are_excluded_and_counted():
    res = evaluate([row(1), row(2, limit_up=True)], params(), COSTS, "train")
    assert res["stats"]["n"] == 1 and res["excluded"]["limit_up"] == 1


def test_missing_exit_price_is_counted_not_filled():
    opens = {0: 10500.0, 1: None, 2: None, 3: None, 4: None, 5: None, 6: None}
    res = evaluate([row(1, opens=opens), row(2)], params(), COSTS, "train")
    assert res["stats"]["n"] == 1 and res["excluded"]["no_exit_price"] == 1


def test_only_the_requested_split_is_evaluated():
    rows = [row(1, split="train"), row(2, split="valid"), row(3, split="none")]
    assert evaluate(rows, params(), COSTS, "train")["stats"]["n"] == 1
    assert evaluate(rows, params(), COSTS, "valid")["stats"]["n"] == 1


def test_lookahead_flag_is_set_only_when_listing_day_conditions_meet_a_close_entry():
    d0 = dict(d0_ret_vs_offer=(0, 100))
    assert evaluate([row(1)], params(**d0), COSTS, "train")["lookahead"] is True
    assert evaluate([row(1)], params(entry="d1_open", **d0), COSTS, "train")["lookahead"] is False
    assert evaluate([row(1)], params(float_pct=(0, 2)), COSTS, "train")["lookahead"] is False


def test_baseline_is_the_same_entry_and_hold_without_any_condition():
    rows = [row(1, float_pct=1.5), row(2, float_pct=0.2, opens={0: 1.0, 1: 9000.0, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1})]
    res = evaluate(rows, params(float_pct=(1.0, 2.0)), COSTS, "train")
    assert res["stats"]["n"] == 1 and res["baseline"]["n"] == 2
    assert res["baseline"]["mean"] < res["stats"]["mean"]


def test_tax_year_comes_from_the_listing_date_and_a_missing_year_raises():
    r26 = row(1, date="20260105")
    assert evaluate([r26], params(), COSTS, "train")["trades"][0]["net_ret"] == pytest.approx(net(11110.0, 11000.0, tax=0.002))
    with pytest.raises(ValueError, match="2030"):
        evaluate([row(1, date="20300102")], params(), COSTS, "train")
