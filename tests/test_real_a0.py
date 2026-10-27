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


def test_run_writes_result_csv_and_doc(world):
    out = real_a0.run("20230106")
    assert Path(out["csv"]).exists() and Path(out["doc"]).exists()
    rows = list(csv.DictReader(open(out["csv"], encoding="utf-8-sig")))
    assert {r["ipo_id"] for r in rows} == {"A_ipo", "LU_ipo"}
    text = Path(out["doc"]).read_text(encoding="utf-8")
    for must in ("기간", "슬리피지", "상한가", "코스닥 기준선", "계산 불가"):
        assert must in text
