"""수요 지표 마트(data/2_mart/dart_demand.csv) 만들기: 종목별로 어떤 공시를 읽을지 고르고, 못 읽으면 조용히 0 으로 채우지 않는다.
시험 대상: build_demand_mart.collect_ipo / write 경로. 파서 자체는 tests/test_dart_demand.py. 요청: '이 데이터들도 수집기를 만들어서 돌아가게 해줘'."""
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_demand_mart as bdm  # noqa: E402
import dart_demand  # noqa: E402

REG = {"ipo_id": "C1_20230102000001", "corp_code": "C1", "stock_code": "111111", "corp_name": "가나다", "list_dd": "20230120"}
TERMS = [
    {"ipo_id": "C1_20230102000001", "rcept_no": "20230102000001", "rcept_dt": "20230102", "kind": "증권신고서", "stock_cnt": ""},
    {"ipo_id": "C1_20230102000001", "rcept_no": "20230110000002", "rcept_dt": "20230110", "kind": "발행조건확정", "stock_cnt": "1000000"},
    {"ipo_id": "C1_20230102000001", "rcept_no": "20230112000003", "rcept_dt": "20230112", "kind": "발행조건확정", "stock_cnt": "1000000"},
    {"ipo_id": "C1_20230102000001", "rcept_no": "20230125000004", "rcept_dt": "20230125", "kind": "발행조건확정", "stock_cnt": "500000"},   # 상장 뒤: 다른 공모
]
REPORTS = [{"rcept_no": "20230118000009", "rcept_dt": "20230118"}, {"rcept_no": "20230301000009", "rcept_dt": "20230301"}]


def fake_demand(ratio, status="확인", **extra):
    base = dart_demand._empty_demand()
    base.update(demand_n=10, demand_qty=1000, demand_ratio=ratio, demand_status=status, demand_note="")
    base.update(extra)
    return base


@pytest.fixture
def docs(monkeypatch):
    calls = []
    by_no = {"20230110000002": fake_demand(50.0), "20230112000003": fake_demand(None, "미확인"),
             "20230102000001": fake_demand(None, "미확인", float_shares=300_000, float_pct=30.0, listed_shares=1_000_000, float_status="확인")}
    monkeypatch.setattr(dart_demand, "demand_for", lambda no, offer_shares=None: (calls.append(("d", no, offer_shares)) or by_no[no]))
    alloc = {"retail_ratio": 800.0, "retail_subscribers": 5, "final_commit_ratio": 0.2, "final_commit_pct": {"6m": 1.0, "3m": 19.0, "1m": 0.0, "15d": 0.0},
             "alloc_status": "확인", "alloc_note": ""}
    monkeypatch.setattr(dart_demand, "allocation_for", lambda no: (calls.append(("a", no)) or alloc))
    return calls


def test_picks_the_latest_pre_listing_filing_that_has_a_demand_table(docs):
    row = bdm.collect_ipo(REG, TERMS, REPORTS)
    assert row["demand_rcept"] == "20230110000002" and row["demand_ratio"] == 50.0
    assert row["demand_available_dt"] == "20230110"
    assert [c for c in docs if c[0] == "d"][0][1] == "20230112000003"          # 가장 늦은 공시부터 열어 본다
    assert all(c[1] != "20230125000004" for c in docs)                           # 상장 뒤 공시는 읽지 않는다


def test_each_group_comes_from_the_latest_filing_that_contains_it(docs):
    row = bdm.collect_ipo(REG, TERMS, REPORTS)
    assert row["float_shares"] == 300_000 and row["float_rcept"] == "20230102000001" and row["float_available_dt"] == "20230102"
    assert row["demand_rcept"] == "20230110000002"                              # 수요예측은 더 늦은 정정 공시에서
    assert row["commit_ratio"] is None and row["commit_status"] == "미확인"       # 어느 공시에도 확약 표가 없으면 빈 칸


def test_offer_shares_from_the_filing_are_passed_for_the_cross_check(docs):
    bdm.collect_ipo(REG, TERMS, REPORTS)
    assert ("d", "20230112000003", 1_000_000.0) in docs


def test_result_report_is_the_first_one_after_the_confirmation_and_before_listing(docs):
    row = bdm.collect_ipo(REG, TERMS, REPORTS)
    assert row["alloc_rcept"] == "20230118000009" and row["alloc_available_dt"] == "20230118"
    assert row["retail_ratio"] == 800.0 and row["final_commit_ratio"] == 0.2 and row["final_commit_3m_pct"] == 19.0


def test_no_filing_means_unknown_values_not_zeros(docs):
    row = bdm.collect_ipo(REG, [], [])
    assert row["demand_ratio"] is None and row["demand_status"] == "미확인" and "공시 없음" in row["demand_note"]
    assert row["retail_ratio"] is None and row["alloc_status"] == "미확인"


def test_a_filing_that_cannot_be_fetched_is_reported_and_does_not_stop_the_build(monkeypatch):
    def boom(no, offer_shares=None):
        raise RuntimeError("DART document.xml 오류")
    monkeypatch.setattr(dart_demand, "demand_for", boom)
    monkeypatch.setattr(dart_demand, "allocation_for", lambda no: dart_demand.parse_allocation(""))
    row = bdm.collect_ipo(REG, TERMS, REPORTS)
    assert row["demand_ratio"] is None and "원문 조회 실패" in row["demand_note"]


def test_lockup_schedule_is_stored_as_json_and_commit_quantities_are_flattened(monkeypatch):
    d = fake_demand(30.0, commit_qty={"6m": 1, "3m": 2, "1m": 3, "15d": 4}, commit_ratio=0.1, lockups={6: 300, 12: 300}, locked_total=600)
    monkeypatch.setattr(dart_demand, "demand_for", lambda no, offer_shares=None: d)
    monkeypatch.setattr(dart_demand, "allocation_for", lambda no: dart_demand.parse_allocation(""))
    row = bdm.collect_ipo(REG, TERMS, [])
    assert row["lockups"] == '{"6": 300, "12": 300}' and row["commit_3m_qty"] == 2 and row["commit_15d_qty"] == 4
    assert row["lockup_coverage"] == 1.0


def test_write_creates_a_csv_with_empty_cells_for_unknowns(tmp_path, monkeypatch, docs):
    import config
    monkeypatch.setattr(config, "MART", tmp_path)
    rows = [bdm.collect_ipo(REG, TERMS, REPORTS), bdm.collect_ipo({**REG, "ipo_id": "X"}, [], [])]
    out = bdm.write(rows)
    read = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    assert [r["ipo_id"] for r in read] == ["C1_20230102000001", "X"]
    assert read[0]["demand_ratio"] == "50.0" and read[1]["demand_ratio"] == ""
