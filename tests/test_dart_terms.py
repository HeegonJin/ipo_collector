import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dart_terms  # noqa: E402

# 디티에스 발행조건확정(2026-10-12) 원문에서 발췌한 실제 문장
REAL = ("제시 공모희망가액인 17,000원 ~ 18,500원 중 최저가액인 17,000원 기준입니다. "
        "정정 후 1. 공모개요 (단위 : 원, 주) 증권의 종류 증권 수량 액면가액 모집(매출)가액 모집(매출)총액 모집(매출)방법 "
        "기명식 보통주 2,228,917 5,000 18,500 41,234,964,500 일반공모 인수인 증권의 종류 인수수량")


def test_parses_confirmed_price_and_band():
    t = dart_terms.parse_offer_terms(REAL)
    assert t["offer_price"] == 18500.0 and t["stock_cnt"] == 2_228_917 and t["offer_amount"] == 41_234_964_500
    assert (t["band_low"], t["band_high"]) == (17000.0, 18500.0) and t["sale_method"] == "일반공모"
    assert t["status"] == "확인"


def test_last_table_wins_when_before_and_after_tables_exist():
    before = REAL.replace("18,500 41,234,964,500", "17,000 37,891,589,000")
    t = dart_terms.parse_offer_terms(before + " " + REAL)
    assert t["offer_price"] == 18500.0


def test_total_mismatch_is_unverified_not_confirmed():
    t = dart_terms.parse_offer_terms(REAL.replace("41,234,964,500", "41,000,000,000"))
    assert t["status"] == "미확인" and t["offer_price"] == 18500.0


# 엠에스바이오 발행조건확정 원문 형태: 정정 전 표는 머리글에 띄어쓰기가 없고, 정정 후 표는 '모집(매출) 방법'
MSBIO = ("(주1) 정정 전 1. 공모개요 (단위: 원, 주) 증권의종류 증권수량 액면가액 모집(매출)가액 모집(매출)총액 모집(매출)방법 "
         "보통주 4,000,000 100 6,800 27,200,000,000 일반공모 인수인 "
         "(주1) 정정 후 1. 공모개요 (단위: 원, 주) 증권의 종류 증권수량 액면가액 모집(매출) 가액 모집(매출) 총액 모집(매출) 방법 "
         "보통주 4,000,000 100 7,800 31,200,000,000 일반공모 인수인 "
         "확정공모가액은 7,800원으로 결정되었습니다.")


def test_after_correction_table_with_spaced_header_beats_before_table():
    t = dart_terms.parse_offer_terms(MSBIO)
    assert t["offer_price"] == 7800.0 and t["status"] == "확인"


def test_only_before_correction_table_is_not_confirmed():
    t = dart_terms.parse_offer_terms(MSBIO.split("(주1) 정정 후")[0])
    assert t["offer_price"] is None and t["status"] == "미확인"


def test_sentence_price_conflicting_with_table_is_unverified():
    t = dart_terms.parse_offer_terms(MSBIO.replace("7,800원으로 결정", "9,000원으로 결정"))
    assert t["status"] == "미확인" and "9000" in t["note"].replace(",", "").replace(".0", "")


def test_missing_table_gives_none_not_zero():
    t = dart_terms.parse_offer_terms("공모 내용 없음")
    assert t["offer_price"] is None and t["status"] == "미확인"


def table(*rows):
    head = ("정정 후 1. 공모개요 (단위 : 원, 주) 증권의 종류 증권 수량 액면가액 모집(매출) 가액 모집(매출) 총액 모집(매출) 방법 ")
    return head + " ".join(rows) + " 인수인 증권의 종류"


def test_preferred_stock_only_offering_is_parsed():
    t = dart_terms.parse_offer_terms(table("기명식 상환전환우선주 1,000,000 500 10,000 10,000,000,000 일반공모"))
    assert t["offer_price"] == 10000.0 and t["stock_kind"] == "상환전환우선주" and t["status"] == "확인"


def test_common_stock_row_wins_when_a_table_lists_several_kinds():
    t = dart_terms.parse_offer_terms(table("기명식 우선주 500,000 500 9,000 4,500,000,000 일반공모",
                                           "기명식 보통주 2,000,000 500 12,000 24,000,000,000 일반공모"))
    assert t["offer_price"] == 12000.0 and t["stock_kind"] == "보통주"


def test_common_stock_still_parses_and_reports_its_kind():
    assert dart_terms.parse_offer_terms(REAL)["stock_kind"] == "보통주"


def test_result_report_preferred_stock_row_is_parsed():
    r = dart_terms.parse_result_report("모집 기명식 우선주 10,000,000,000 10,000 1,000,000 10,000,000,000")
    assert r["issue_price"] == 10000.0 and r["status"] == "확인"


# 진코스텍 증권발행실적보고서(2026-10-08) 원문에서 발췌한 실제 문장
RESULT = ("Ⅵ. 조달된 자금의 사용내역 1. 자금조달 내용 (단위 : 원, 주) 구분 주식구분 신고서상발행예정총액 실제 조달금액 비고 "
          "발행가액 수 량 발행총액 모집 보통주 20,022,000,000 23,500 852,000 20,022,000,000 - 계 20,022,000,000 23,500 852,000")


def final(price=23500.0, status="확인"):
    return {"offer_price": price, "status": status, "rcept_no": "R1", "note": ""}


def test_parse_result_report_reads_actual_issue_price():
    r = dart_terms.parse_result_report(RESULT)
    assert r["issue_price"] == 23500.0 and r["stock_cnt"] == 852_000 and r["status"] == "확인"


def test_parse_result_report_without_table_is_unverified_not_zero():
    r = dart_terms.parse_result_report("자금조달 내용 없음")
    assert r["issue_price"] is None and r["status"] == "미확인"


def test_reconcile_matching_result_report_marks_crosscheck_ok():
    out = dart_terms.reconcile(final(), dart_terms.parse_result_report(RESULT))
    assert out["status"] == "확인" and out["crosscheck"] == "일치"


def test_reconcile_conflict_downgrades_to_unverified_and_keeps_both_values():
    out = dart_terms.reconcile(final(23850.0), dart_terms.parse_result_report(RESULT))
    assert out["status"] == "미확인" and out["crosscheck"] == "불일치"
    assert "23850" in out["note"].replace(",", "").replace(".0", "") and "23500" in out["note"].replace(",", "").replace(".0", "")


def test_reconcile_without_result_report_keeps_status_and_says_not_checked():
    out = dart_terms.reconcile(final(), None)
    assert out["status"] == "확인" and out["crosscheck"] == "미실시"


def test_reconcile_never_upgrades_an_unverified_price():
    out = dart_terms.reconcile(final(23500.0, "미확인"), dart_terms.parse_result_report(RESULT))
    assert out["status"] == "미확인"


def test_to_text_strips_tags_and_entities():
    assert dart_terms.to_text("<P>A&amp;B</P>\n<TD>1,000</TD>") == " A&B 1,000 "
