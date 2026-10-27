import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_dart_registry as b  # noqa: E402


def reg(corp, no, dt, kind, name="가나다"):
    return {"corp_code": corp, "rcept_no": no, "rcept_dt": dt, "kind": kind, "corp_name": name,
            "report_nm": "x", "stock_code": ""}


def patch(monkeypatch, regs, listing, fetched, result_reports=None, result_price=None,
          sale_method="일반공모", final_price=18500.0):
    monkeypatch.setattr(b.dart_list, "equity_registrations", lambda s, e: regs)
    monkeypatch.setattr(b.dart_list, "result_reports", lambda s, e: result_reports or {})
    monkeypatch.setattr(b.dart_terms, "result_report_terms", lambda rcept: {
        "issue_price": result_price, "status": "확인" if result_price else "미확인"})
    monkeypatch.setattr(b, "krx_listing_dates", lambda d: listing)
    monkeypatch.setattr(b.dart_estk, "estk_for_corp",
                        # 실제 estkRs 는 발행조건확정이 아닌 가장 최신 정정본 한 건을 돌려준다
                        lambda corp, fl: [{"rcept_no": [f for f in fl if f["kind"] != "발행조건확정"][-1]["rcept_no"],
                                           "corp_code": corp, "corp_name": "n",
                                           "offer_price": 17000.0, "sale_method": "일반공모"}])

    def fake_final(rcepts):
        fetched.append(list(rcepts))
        return {"offer_price": final_price, "status": "확인" if final_price else "미확인", "rcept_no": sorted(rcepts)[-1],
                "band_low": 17000.0, "band_high": 18500.0, "note": "" if final_price else "공모개요 표 없음",
                "sale_method": sale_method}

    monkeypatch.setattr(b.dart_terms, "final_offer_terms", fake_final)


def test_final_price_attached_only_to_chosen_filing_and_expected_kept_separate(monkeypatch):
    fetched = []
    regs = [reg("00000001", "20260911000314", "20260911", "최초"),
            reg("00000001", "20261001000078", "20261001", "기재정정"),
            reg("00000001", "20261012000308", "20261012", "발행조건확정")]
    patch(monkeypatch, regs, {"00000001": ("123456", "20261023")}, fetched)
    registry, terms = b.build("20260101", "20261027", "20261023")
    (r,) = registry
    assert r["ipo_id"] == "00000001_20260911000314" and r["in_trading_universe"] is True
    assert r["offer_price_final"] == 18500.0 and r["offer_price_status"] == "확인"
    by = {t["rcept_no"]: t for t in terms}
    assert by["20261012000308"]["offer_price"] == 18500.0
    assert by["20261001000078"]["offer_price"] is None and by["20261001000078"]["offer_price_expected"] == 17000.0
    assert by["20260911000314"]["available_at"] == "2026-09-11T23:59:59+09:00"
    assert fetched == [["20261012000308"]]


def test_documents_not_fetched_for_corps_outside_trading_universe(monkeypatch):
    fetched = []
    regs = [reg("00000002", "20260911000999", "20260911", "최초"),
            reg("00000002", "20261012000998", "20261012", "발행조건확정")]
    patch(monkeypatch, regs, {}, fetched)  # KRX 상장 정보 없음 → 대상 아님
    (r,), _ = b.build("20260101", "20261027", "20261023")
    assert r["in_trading_universe"] is False and fetched == []
    assert r["offer_price_final"] is None and r["offer_price_status"] == "미확인"


RR = {"00000001": [{"rcept_no": "20261014000500", "rcept_dt": "20261014"}]}
REGS = [reg("00000001", "20260911000314", "20260911", "최초"),
        reg("00000001", "20261012000308", "20261012", "발행조건확정")]


def test_matching_result_report_marks_crosscheck_ok(monkeypatch):
    patch(monkeypatch, REGS, {"00000001": ("123456", "20261023")}, [], RR, result_price=18500.0)
    (r,), _ = b.build("20260101", "20261027", "20261023")
    assert r["offer_price_crosscheck"] == "일치" and r["offer_price_status"] == "확인"


def test_conflicting_result_report_downgrades_the_confirmed_price(monkeypatch):
    patch(monkeypatch, REGS, {"00000001": ("123456", "20261023")}, [], RR, result_price=17000.0)
    (r,), terms = b.build("20260101", "20261027", "20261023")
    assert r["offer_price_crosscheck"] == "불일치" and r["offer_price_status"] == "미확인"
    assert "17000" in r["offer_price_note"] and "18500" in r["offer_price_note"]
    assert {t["offer_price_status"] for t in terms} == {"미확인"}      # 공시 버전 표에도 확인으로 남지 않는다


def test_missing_result_report_is_not_checked_but_not_downgraded(monkeypatch):
    patch(monkeypatch, REGS, {"00000001": ("123456", "20261023")}, [], {}, result_price=None)
    (r,), _ = b.build("20260101", "20261027", "20261023")
    assert r["offer_price_crosscheck"] == "미실시" and r["offer_price_status"] == "확인"


def test_krx_snapshot_failure_raises_instead_of_silently_emptying_the_universe(monkeypatch):
    def boom(service, d):
        raise RuntimeError("401")
    monkeypatch.setattr(b.krx_api, "fetch", boom)
    with pytest.raises(RuntimeError, match="ksq_base"):
        b.krx_listing_dates("20261023")


def test_empty_krx_snapshot_raises(monkeypatch):
    monkeypatch.setattr(b.krx_api, "fetch", lambda service, d: [])
    with pytest.raises(RuntimeError, match="비어"):
        b.krx_listing_dates("20261023")


def test_krx_snapshot_maps_corp_to_stock_and_listing_date(monkeypatch):
    monkeypatch.setattr(b.krx_api, "fetch", lambda service, d: [{"ISU_SRT_CD": "195990", "LIST_DD": "20261023"}])
    monkeypatch.setattr(b.dart_api, "corp_code_map", lambda: {"195990": "00534729", "000000": "00000009"})
    assert b.krx_listing_dates("20261023") == {"00534729": ("195990", "20261023")}


def test_confirming_filings_after_listing_are_other_offerings_and_are_ignored(monkeypatch):
    """상장 뒤의 발행조건확정 공시는 유상증자 등 다른 공모다 (이노스페이스·센서뷰 사례) — IPO 확정가 후보에서 뺀다."""
    fetched = []
    regs = REGS + [reg("00000001", "20270115000900", "20270115", "발행조건확정")]
    patch(monkeypatch, regs, {"00000001": ("123456", "20261023")}, fetched)
    (r,), terms = b.build("20260101", "20270201", "20261023")
    assert fetched == [["20261012000308"]]
    assert r["offer_price_rcept"] == "20261012000308"


def test_non_public_offering_method_is_not_trusted_as_an_ipo_price(monkeypatch):
    patch(monkeypatch, REGS, {"00000001": ("123456", "20261023")}, [], sale_method="주주배정")
    (r,), _ = b.build("20260101", "20261027", "20261023")
    assert r["offer_price_status"] == "미확인" and "일반공모" in r["offer_price_note"]


def test_result_report_price_is_adopted_when_the_confirming_filing_has_no_readable_price(monkeypatch):
    patch(monkeypatch, REGS, {"00000001": ("123456", "20261023")}, [], RR, result_price=18500.0, final_price=None)
    (r,), _ = b.build("20260101", "20261027", "20261023")
    assert r["offer_price_final"] == 18500.0 and r["offer_price_status"] == "확인"
    assert r["offer_price_crosscheck"] == "실적보고서 단독"
    assert r["offer_price_rcept"] == "20261014000500" and r["offer_price_available_dt"] == "20261014"


def test_available_date_of_a_normal_price_is_the_confirming_filing_date(monkeypatch):
    patch(monkeypatch, REGS, {"00000001": ("123456", "20261023")}, [])
    (r,), _ = b.build("20260101", "20261027", "20261023")
    assert r["offer_price_available_dt"] == "20261012"


def test_universe_excludes_listings_before_the_sample_start_and_konex_transfers():
    # 첫 인자는 '상장 직전 마지막 지분증권 신고일' (없으면 None)
    assert b.universe_decision("20261012", "20261023", "20230701", None) == (True, "")
    assert b.universe_decision("20230109", "20230119", "20230701", None) == (False, "표본 시작일 이전 상장")
    assert b.universe_decision("20241011", "20241025", "20230701", "코넥스 이전상장") == (False, "코넥스 이전상장")
    assert b.universe_decision("20261012", "", "20230701", None) == (False, "KRX 상장일 없음")
    assert b.universe_decision(None, "20250101", "20230701", None)[0] is False       # 상장 전 신고 없음: 합병·이전상장
    assert b.universe_decision("20240101", "20260101", "20230701", None)[0] is False  # 마지막 신고도 400일 초과


def test_refiled_ipo_is_in_the_universe_even_if_the_first_filing_was_withdrawn_long_before(monkeypatch):
    """알지노믹스: 최초 신고 2024-08(철회), 재신고 뒤 2025-12 상장 — 최초 신고일 기준 400일 창이면 놓친다."""
    regs = [reg("00000007", "20240829000100", "20240829", "최초"),
            reg("00000007", "20251205000200", "20251205", "발행조건확정")]
    patch(monkeypatch, regs, {"00000007": ("476830", "20251218")}, [])
    (r,), _ = b.build("20230101", "20261027", "20261023")
    assert r["in_trading_universe"] is True and r["ipo_id"] == "00000007_20240829000100"


def test_filings_only_after_listing_mean_an_existing_company_not_an_ipo(monkeypatch):
    regs = [reg("00000008", "20260109000100", "20260109", "최초"), reg("00000008", "20260209000200", "20260209", "발행조건확정")]
    patch(monkeypatch, regs, {"00000008": ("199550", "20240201")}, [])
    (r,), _ = b.build("20230101", "20261027", "20261023")
    assert r["in_trading_universe"] is False


def test_build_applies_the_exclusions_to_the_registry(monkeypatch):
    patch(monkeypatch, REGS, {"00000001": ("123456", "20261023")}, [])
    (r,), _ = b.build("20260101", "20261027", "20261023", exclude={"123456": "코넥스 이전상장"})
    assert r["in_trading_universe"] is False and r["universe_note"] == "코넥스 이전상장"


def test_listing_window():
    assert b.listed_within_window("20260911", "20261023") is True
    assert b.listed_within_window("20260911", "20260101") is False   # 신고보다 먼저 상장 → 기존 상장사
    assert b.listed_within_window("20250101", "20261023") is False   # 400일 초과
    assert b.listed_within_window("20260911", "") is False
