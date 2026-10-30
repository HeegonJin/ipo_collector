"""레지스트리·공모 조건 CSV + KRX raw → A0 정산 결과. (가짜 raw 와 가짜 CSV 로 배선 검증)"""
import csv
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_dart_registry as b  # noqa: E402
import config  # noqa: E402
import test_logic  # noqa: E402
from core import settings  # noqa: E402
from evaluate import real_a0  # noqa: E402
from store.bars import CALENDAR_CODE, calendar_bars, iter_filtered_bars  # noqa: E402


def reg(ipo_id, code, list_dd, price="10000.0"):
    return {"ipo_id": ipo_id, "corp_code": "0", "stock_code": code, "corp_name": code, "first_rcept_no": "R0",
            "first_rcept_dt": "20230102", "sale_method": "일반공모", "is_ipo_candidate": True, "list_dd": list_dd,
            "in_trading_universe": True, "n_filings": 2, "last_kind": "발행조건확정", "offer_price_final": price,
            "offer_price_status": "확인", "offer_price_rcept": "R1", "band_low": None, "band_high": None,
            "offer_price_note": ""}


@pytest.fixture
def world(monkeypatch):
    for name in ("RAW", "MART", "META", "ROOT", "BUFFER_START", "SAMPLE_START"):
        monkeypatch.setattr(config, name, getattr(config, name))
    tmp = Path(tempfile.mkdtemp())
    test_logic.setup(tmp)
    b.write([reg("A_ipo", "A", "20230105"), reg("LU_ipo", "LU", "20230105")], b.REGISTRY_COLS, "dart_ipo_registry.csv")
    b.write([{"ipo_id": "A_ipo", "rcept_no": "R1", "rcept_dt": "20230103", "kind": "발행조건확정",
              "available_at": b.available_at("20230103")},
             {"ipo_id": "LU_ipo", "rcept_no": "R1", "rcept_dt": "20230103", "kind": "발행조건확정",
              "available_at": b.available_at("20230103")}], b.TERMS_COLS, "dart_offer_terms.csv")
    return tmp


def test_iter_filtered_bars_keeps_only_requested_codes(world):
    bars = list(iter_filtered_bars("20230103", "20230106", {"A"}))
    assert {x["short_code"] for x in bars} == {"A"} and [x["date"] for x in bars] == ["20230105", "20230106"]


def test_iter_index_bars_reads_the_kosdaq_row_of_each_day(world):
    from store.bars import INDEX_CODE, iter_index_bars
    bars = list(iter_index_bars("20230103", "20230106"))
    assert [b_["date"] for b_ in bars] == ["20230103", "20230104", "20230105", "20230106"]
    assert {b_["short_code"] for b_ in bars} == {INDEX_CODE}
    assert (bars[-1]["open"], bars[-1]["close"]) == (707.0, 710.0)


def test_benchmark_and_excess_return_use_the_index_when_it_is_collected(world):
    out = real_a0.run("20230106")
    by = {r["ipo_id"]: r for r in out["rows"]}
    assert by["A_ipo"]["bench_ret"] == pytest.approx(707 / 700 - 1)         # 0105 종가 → 0106 시가
    assert out["summary_bench"]["n"] >= 1
    # 초과수익은 주 결과와 같은 표본(상한가 아님 확인 건 = A) 의 종목별 (순수익 − 기준선)
    assert out["summary_excess"]["n"] == 1
    assert out["summary_excess"]["mean"] == pytest.approx(by["A_ipo"]["net_ret"] - (707 / 700 - 1))
    text = Path(out["doc"]).read_text(encoding="utf-8")
    assert "초과수익" in text and "D12" in text and "기대값 > 0" in text and "미승인" not in text


def test_without_index_data_the_benchmark_is_not_computable_and_says_so(world):
    import shutil
    shutil.rmtree(config.RAW / "krx" / "kosdaq_idx")
    out = real_a0.run("20230106")
    assert out["summary_bench"] is None and out["summary_excess"] is None
    assert "계산 불가" in Path(out["doc"]).read_text(encoding="utf-8")


def test_last_seen_dates_finds_stocks_that_stop_appearing(world):
    import json
    from store.bars import last_seen_dates
    p = config.RAW / "krx" / "ksq_daily" / "20230105.json"
    rows = json.loads(p.read_text(encoding="utf-8"))
    rows.append(test_logic.row("GONE", "폐지기업", 5000, -5000))      # 0105 에만 등장
    p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    seen, last_day = last_seen_dates("20230103", "20230106")
    assert last_day == "20230106"
    assert seen["GONE"] == "20230105" and seen["A"] == "20230106" and seen["OLD"] == "20230106"


def test_calendar_bars_give_one_marker_per_trading_day(world):
    cal = calendar_bars("20230103", "20230106")
    assert [c["date"] for c in cal] == ["20230103", "20230104", "20230105", "20230106"]
    assert {c["short_code"] for c in cal} == {CALENDAR_CODE}


def test_run_settles_registry_ipos_with_yaml_costs(world):
    out = real_a0.run("20230106")
    by = {r["ipo_id"]: r for r in out["rows"]}
    c = settings.load_costs(2023, 2023)
    fee, slip, tax = c["commission_per_side"], c["slippage_per_side"], c["kosdaq_sell_tax"][2023]
    assert by["A_ipo"]["entry_px"] == 6800 and by["A_ipo"]["exit_px"] == 7700
    assert by["A_ipo"]["net_ret"] == pytest.approx(7700 * (1 - fee - slip - tax) / (6800 * (1 + fee + slip)) - 1)
    assert by["LU_ipo"]["buy_at_limit_up"] is True and by["A_ipo"]["buy_at_limit_up"] is False
    assert out["summary"]["n"] == 2


def test_unknown_limit_up_is_reported_separately_not_counted_as_fillable(world):
    """공모가를 몰라 상한가 여부를 판정할 수 없는 건은 주 결과(상한가 제외)에 넣지 않고 따로 보고한다."""
    unknown = reg("U_ipo", "SP", "20230105", price="")
    unknown["offer_price_status"] = "미확인"
    b.write([reg("A_ipo", "A", "20230105"), reg("LU_ipo", "LU", "20230105"), unknown], b.REGISTRY_COLS,
            "dart_ipo_registry.csv")
    b.write([{"ipo_id": i, "rcept_no": "R1", "rcept_dt": "20230103", "kind": "발행조건확정",
              "available_at": b.available_at("20230103")} for i in ("A_ipo", "LU_ipo", "U_ipo")],
            b.TERMS_COLS, "dart_offer_terms.csv")
    out = real_a0.run("20230106")
    by = {r["ipo_id"]: r for r in out["rows"]}
    assert by["U_ipo"]["buy_at_limit_up"] is None
    assert out["summary"]["n"] == 3                       # 전부 체결 가정
    assert out["summary_ex_limit_up"]["n"] == 1           # 상한가가 아님이 확인된 건(A)만
    assert out["summary_unknown"]["n"] == 1               # 불명은 따로
    assert "상한가 불명" in Path(out["doc"]).read_text(encoding="utf-8")


def test_delisted_stock_is_reported_and_sensitivities_include_it(world):
    """상장일 다음 날부터 일별 데이터에서 사라진 종목은 통계에서 조용히 빠지지 않고 폐지로 보고된다."""
    import json
    p = config.RAW / "krx" / "ksq_daily" / "20230105.json"
    rows = json.loads(p.read_text(encoding="utf-8"))
    rows.append(test_logic.row("GONE", "폐지기업", 5000, -5000))          # 공모가 10,000 → 종가 5,000, 이후 사라짐
    p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    b.write([reg("A_ipo", "A", "20230105"), reg("LU_ipo", "LU", "20230105"), reg("G_ipo", "GONE", "20230105")],
            b.REGISTRY_COLS, "dart_ipo_registry.csv")
    b.write([{"ipo_id": i, "rcept_no": "R1", "rcept_dt": "20230103", "kind": "발행조건확정",
              "available_at": b.available_at("20230103")} for i in ("A_ipo", "LU_ipo", "G_ipo")],
            b.TERMS_COLS, "dart_offer_terms.csv")
    out = real_a0.run("20230106")
    by = {r["ipo_id"]: r for r in out["rows"]}
    assert by["G_ipo"]["exit_kind"] == "폐지" and by["G_ipo"]["net_ret"] is None
    assert out["summary_ex_limit_up"]["n"] == 1                             # 주 결과는 그대로 (폐지 건은 계산 불가)
    assert out["exit_issues"] == {"폐지": 1}
    a_net = by["A_ipo"]["net_ret"]
    assert out["summary_wipeout"]["n"] == 2 and out["summary_wipeout"]["mean"] == pytest.approx((a_net - 1.0) / 2)
    assert out["summary_last_close"]["n"] == 2 and out["summary_last_close"]["mean"] > out["summary_wipeout"]["mean"]
    text = Path(out["doc"]).read_text(encoding="utf-8")
    assert "폐지/거래정지" in text and "전손" in text and "마지막 종가" in text


def test_run_writes_result_csv_and_doc(world):
    out = real_a0.run("20230106")
    assert Path(out["csv"]).exists() and Path(out["doc"]).exists()
    rows = list(csv.DictReader(open(out["csv"], encoding="utf-8-sig")))
    assert {r["ipo_id"] for r in rows} == {"A_ipo", "LU_ipo"}
    text = Path(out["doc"]).read_text(encoding="utf-8")
    for must in ("기간", "슬리피지", "상한가", "코스닥 기준선", "계산 불가"):
        assert must in text
