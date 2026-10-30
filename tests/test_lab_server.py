"""전략 실험 앱 서버: 핸들러(Lab)와 로컬 HTTP 껍데기. 요청: '각 조건을 사람이 앱에서 튜닝하면서 테스트' (로컬 앱, 과적합 장치 포함)."""
import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.guards import TrialLog, ValidationGate  # noqa: E402
from lab.server import Lab, make_server  # noqa: E402

COSTS = {"commission_per_side": 0.0, "slippage_per_side": 0.0, "kosdaq_sell_tax": {2025: 0.0}}
CFG = {"min_n": 5, "confirm_phrase": "검증 구간을 엽니다", "trials_warn_at": 3}


def row(i, float_pct, ret, split="train"):
    px = 10000.0 * (1 + ret)
    return {"ipo_id": f"I{i}", "name": f"종목{i}", "code": f"C{i}", "list_date": "20250103", "split": split,
            "offer_price": 10000.0, "float_pct": float_pct, "retail_ratio": 100.0, "d0_ret_vs_offer": 20.0,
            "d0_drop_from_high": -5.0, "d0_index_chg": 0.5, "close_d0": 10000.0,
            "open_d": {k: px for k in range(7)}, "limit_up": False}


def make_lab(tmp_path):
    rows = [row(i, 1.0, 0.02) for i in range(12)] + [row(50 + i, 1.0, 0.01, split="valid") for i in range(8)]
    log = TrialLog(tmp_path / "trials.csv")
    gate = ValidationGate(rows, COSTS, log, tmp_path / "validation_runs.csv", dict(CFG))
    return Lab(rows, COSTS, log, gate, dict(CFG), meta={"train_window": "x"})


P = {"entry": "d0_close", "hold": 1, "conditions": {"float_pct": {"enabled": True, "lo": 0.5, "hi": 1.5}}}


def test_meta_labels_design_external_conditions_and_lookahead_phases(tmp_path):
    meta = make_lab(tmp_path).meta()
    conds = {c["id"]: c for c in meta["conditions"]}
    assert conds["float_pct"]["in_design"] is True and conds["d0_ret_vs_offer"]["phase"] == "d0"
    assert meta["entries"]["d1_open"]["in_design"] is False and meta["min_n"] == 5


def test_meta_reports_how_many_training_stocks_have_a_value_for_each_condition(tmp_path):
    lab = make_lab(tmp_path)
    lab.rows[0]["float_pct"] = None                              # 값을 모르는 종목은 센다 → 조건을 켜면 그만큼 제외된다
    cov = lab.meta()["coverage"]
    assert cov["float_pct"] == 11 and cov["d0_ret_vs_offer"] == 12


def test_count_reports_n_without_counting_a_trial(tmp_path):
    lab = make_lab(tmp_path)
    assert lab.count(P)["n"] == 12
    assert lab.trials.distinct() == 0


def test_evaluate_records_a_trial_and_returns_guardrails(tmp_path):
    lab = make_lab(tmp_path)
    out = lab.evaluate(P)
    assert out["stats"]["n"] == 12 and out["stats"]["insufficient"] is False
    assert out["trials"]["distinct"] == 1 and out["trials"]["warn"] is False
    assert out["robustness"]["verdict"] in ("견고", "취약", "판단 불가") and out["split"] == "train"
    lab.evaluate(P)                                           # 같은 조합은 새 시도가 아니다
    assert lab.trials.distinct() == 1
    other = {**P, "hold": 3}
    lab.evaluate(other)
    out = lab.evaluate({**P, "hold": 5})
    assert out["trials"]["distinct"] == 3 and out["trials"]["warn"] is True and out["trials"]["chance_best"] >= 0


def test_evaluate_masks_numbers_below_the_minimum_sample(tmp_path):
    lab = make_lab(tmp_path)
    lab.cfg["min_n"] = 50
    out = lab.evaluate(P)
    assert out["stats"] == {"n": 12, "insufficient": True, "min_n": 50}


def test_evaluate_flags_lookahead_for_d0_conditions_with_d0_close_entry(tmp_path):
    lab = make_lab(tmp_path)
    p = {"entry": "d0_close", "hold": 1, "conditions": {"d0_ret_vs_offer": {"enabled": True, "lo": 0, "hi": 100}}}
    assert lab.evaluate(p)["lookahead"] is True


def test_invalid_params_raise_value_error(tmp_path):
    with pytest.raises(ValueError):
        make_lab(tmp_path).evaluate({"entry": "nope", "hold": 1, "conditions": {}})


def test_validate_requires_phrase_and_prior_train_evaluation(tmp_path):
    lab = make_lab(tmp_path)
    with pytest.raises(PermissionError):
        lab.validate(P, "열어줘", datetime(2026, 11, 1))
    with pytest.raises(PermissionError):
        lab.validate(P, CFG["confirm_phrase"], datetime(2026, 11, 1))
    lab.evaluate(P)
    out = lab.validate(P, CFG["confirm_phrase"], datetime(2026, 11, 1))
    assert out["split"] == "valid" and out["stats"]["n"] == 8


def test_export_yaml_is_parseable_and_carries_provenance(tmp_path):
    lab = make_lab(tmp_path)
    lab.evaluate(P)
    text = lab.export(P)["yaml"]
    doc = yaml.safe_load(text)
    assert doc["entry"] == "d0_close" and doc["hold"] == 1 and doc["conditions"]["float_pct"] == [0.5, 1.5]
    assert doc["trials_distinct"] == 1 and doc["design_external"] == []
    assert "train" in doc["evaluated_on"]


def test_export_marks_the_d1_open_entry_as_design_external(tmp_path):
    lab = make_lab(tmp_path)
    doc = yaml.safe_load(lab.export({**P, "entry": "d1_open"})["yaml"])
    assert doc["design_external"] == ["d1_open"]


def test_trials_lists_history(tmp_path):
    lab = make_lab(tmp_path)
    lab.evaluate(P)
    t = lab.trials_view()
    assert t["distinct"] == 1 and t["items"][0]["hash"]


# ── HTTP 껍데기 ─────────────────────────────────────────────────
@pytest.fixture
def served(tmp_path):
    lab = make_lab(tmp_path)
    srv = make_server(lab, port=0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv.server_address[1], lab
    srv.shutdown()


def call(port, path, body=None, headers=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method or ("POST" if body is not None else "GET"),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_http_meta_and_evaluate_roundtrip(served):
    port, _ = served
    assert call(port, "/api/meta")[0] == 200
    status, out = call(port, "/api/evaluate", {"params": P})
    assert status == 200 and out["stats"]["n"] == 12


def test_http_rejects_foreign_origin_and_foreign_host(served):
    port, _ = served
    assert call(port, "/api/evaluate", {"params": P}, headers={"Origin": "http://evil.example"})[0] == 403
    assert call(port, "/api/meta", headers={"Host": "evil.example"})[0] == 403


def test_http_maps_errors_to_status_codes(served):
    port, _ = served
    assert call(port, "/api/evaluate", {"params": {"entry": "x", "hold": 1, "conditions": {}}})[0] == 400
    assert call(port, "/api/validate", {"params": P, "confirm": "no"})[0] == 403
    assert call(port, "/api/nothing")[0] == 404
    assert call(port, "/api/evaluate", method="GET")[0] == 405          # 평가는 POST 전용
