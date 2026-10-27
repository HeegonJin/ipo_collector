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


def test_to_text_strips_tags_and_entities():
    assert dart_terms.to_text("<P>A&amp;B</P>\n<TD>1,000</TD>") == " A&B 1,000 "
