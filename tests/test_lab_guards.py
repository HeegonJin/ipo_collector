"""전략 실험 앱의 과적합 방지 장치 4가지: 최소 표본 수, 시도 횟수 카운터, 이웃 구간 견고성, 검증 구간 잠금."""
import csv
import math
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.engine import normalize  # noqa: E402
from lab.guards import (TrialLog, ValidationGate, chance_best, load_lab_config, mask, params_hash,  # noqa: E402
                        robustness)

COSTS = {"commission_per_side": 0.0, "slippage_per_side": 0.0, "kosdaq_sell_tax": {2025: 0.0}}


def row(i, float_pct, ret, split="train"):
    px = 10000.0 * (1 + ret)
    return {"ipo_id": f"I{i}", "name": f"종목{i}", "code": f"C{i}", "list_date": "20250103", "split": split,
            "offer_price": 10000.0, "float_pct": float_pct, "retail_ratio": 100.0, "d0_ret_vs_offer": 0.0,
            "d0_drop_from_high": -1.0, "d0_index_chg": 0.0, "close_d0": 10000.0,
            "open_d": {k: px for k in range(7)}, "limit_up": False}


def params(lo, hi, hold=1):
    return {"entry": "d0_close", "hold": hold, "conditions": {"float_pct": {"enabled": True, "lo": lo, "hi": hi}}}


# ── 1. 최소 표본 수 ─────────────────────────────────────────────
def test_below_the_minimum_sample_no_return_numbers_are_shown():
    out = mask({"n": 12, "mean": 0.05, "median": 0.04, "win_rate": 0.7}, min_n=30)
    assert out == {"n": 12, "insufficient": True, "min_n": 30}


def test_enough_samples_keep_the_numbers():
    out = mask({"n": 30, "mean": 0.01}, min_n=30)
    assert out["insufficient"] is False and out["mean"] == 0.01


def test_lab_config_has_a_sane_minimum_and_a_confirmation_phrase():
    cfg = load_lab_config()
    assert cfg["min_n"] >= 20 and isinstance(cfg["confirm_phrase"], str) and len(cfg["confirm_phrase"]) >= 5


# ── 2. 시도 횟수 카운터 ─────────────────────────────────────────
def test_params_hash_ignores_disabled_conditions_and_key_order():
    a = normalize({"entry": "d0_close", "hold": 1, "conditions": {
        "float_pct": {"enabled": True, "lo": 0.5, "hi": 2.0}, "d0_index_chg": {"enabled": False, "lo": -1, "hi": 1}}})
    b = normalize({"conditions": {"float_pct": {"hi": 2.0, "lo": 0.5, "enabled": True}}, "hold": 1, "entry": "d0_close"})
    assert params_hash(a) == params_hash(b) != params_hash(normalize(params(0.5, 2.5)))


def test_only_distinct_parameter_sets_count_as_trials_and_the_count_persists(tmp_path):
    log = TrialLog(tmp_path / "lab_trials.csv")
    p1, p2 = normalize(params(0.5, 2.0)), normalize(params(0.5, 2.5))
    log.record(p1)
    log.record(p1)                                   # 같은 조합을 다시 본 것은 새 시도가 아니다
    log.record(p2)
    assert log.distinct() == 2 and log.total() == 3 and log.seen(params_hash(p1)) and not log.seen("nope")
    assert TrialLog(tmp_path / "lab_trials.csv").distinct() == 2


def test_chance_best_grows_with_the_number_of_trials_and_is_zero_for_a_single_trial():
    assert chance_best(1, 0.01) == 0.0
    assert chance_best(10, 0.01) == pytest.approx(0.01 * math.sqrt(2 * math.log(10)))
    assert chance_best(50, 0.01) > chance_best(10, 0.01) > chance_best(2, 0.01) > 0


# ── 3. 이웃 구간 견고성 ─────────────────────────────────────────
def spiky_rows():
    # 중심(밴드 상단 1.0) 8건만 +10%, 양옆 24건씩은 -10%: 기준값을 한 칸만 넓혀도 평균이 음수로 뒤집힌다
    return ([row(i, 1.0, 0.10) for i in range(8)] + [row(100 + i, 0.75, -0.10) for i in range(24)]
            + [row(200 + i, 1.25, -0.10) for i in range(24)])


def flat_rows():
    return [row(i, bp, 0.02) for i, bp in enumerate([0.75, 1.0, 1.25] * 8)]


def test_a_spike_whose_neighbours_flip_sign_is_flagged_fragile():
    out = robustness(spiky_rows(), params(1.0, 1.0), COSTS, "train", min_n=5)
    assert out["verdict"] == "취약" and any(n["mean"] is not None and n["mean"] < 0 for n in out["neighbors"])


def test_a_stable_edge_is_reported_robust():
    out = robustness(flat_rows(), params(1.0, 1.0), COSTS, "train", min_n=5)
    assert out["verdict"] == "견고"


def test_robustness_hides_neighbours_with_too_few_samples_and_says_when_it_cannot_judge():
    out = robustness(flat_rows(), params(1.0, 1.0), COSTS, "train", min_n=500)
    assert out["verdict"] == "판단 불가" and all(n["mean"] is None for n in out["neighbors"])
    no_cond = robustness(flat_rows(), {"entry": "d0_close", "hold": 1, "conditions": {}}, COSTS, "train", min_n=5)
    assert no_cond["neighbors"] and all("보유" in n["label"] for n in no_cond["neighbors"])   # 조건이 없으면 보유기간 이웃만 본다


# ── 4. 검증 구간 잠금 ───────────────────────────────────────────
def gate_setup(tmp_path):
    rows = [row(i, 1.0, 0.03) for i in range(10)] + [row(50 + i, 1.0, 0.01, split="valid") for i in range(10)]
    log = TrialLog(tmp_path / "trials.csv")
    gate = ValidationGate(rows, COSTS, log, tmp_path / "validation_runs.csv", {"min_n": 5, "confirm_phrase": "검증 구간을 엽니다"})
    return gate, log


def test_validation_stays_locked_without_the_exact_phrase(tmp_path):
    gate, log = gate_setup(tmp_path)
    log.record(normalize(params(0.5, 1.5)))
    with pytest.raises(PermissionError):
        gate.open(params(0.5, 1.5), "열어줘", datetime(2026, 11, 1, 9, 0))
    assert not (tmp_path / "validation_runs.csv").exists()


def test_validation_cannot_be_opened_for_parameters_never_evaluated_on_train(tmp_path):
    gate, _ = gate_setup(tmp_path)
    with pytest.raises(PermissionError, match="학습"):
        gate.open(params(0.5, 1.5), "검증 구간을 엽니다", datetime(2026, 11, 1, 9, 0))


def test_opening_validation_logs_the_candidate_and_the_second_opening_warns(tmp_path):
    gate, log = gate_setup(tmp_path)
    log.record(normalize(params(0.5, 1.5)))
    first = gate.open(params(0.5, 1.5), "검증 구간을 엽니다", datetime(2026, 11, 1, 9, 0))
    second = gate.open(params(0.5, 1.5), "검증 구간을 엽니다", datetime(2026, 11, 2, 9, 0))
    assert first["split"] == "valid" and first["stats"]["n"] == 10 and first["warning"] == ""
    assert "2번째" in second["warning"]
    rows = list(csv.DictReader(open(tmp_path / "validation_runs.csv", encoding="utf-8-sig")))
    assert len(rows) == 2 and rows[0]["tag"].startswith("lab ") and params_hash(normalize(params(0.5, 1.5))) in rows[0]["tag"]


def test_validation_result_respects_the_minimum_sample(tmp_path):
    gate, log = gate_setup(tmp_path)
    log.record(normalize(params(0.5, 1.5)))
    gate.cfg["min_n"] = 50
    out = gate.open(params(0.5, 1.5), "검증 구간을 엽니다", datetime(2026, 11, 1, 9, 0))
    assert out["stats"] == {"n": 10, "insufficient": True, "min_n": 50}
