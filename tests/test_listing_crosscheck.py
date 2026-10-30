"""'일별 데이터에 처음 나타난 날 = 상장일' 규칙을 KRX 종목기본정보의 LIST_DD 로 교차검증한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_sample  # noqa: E402


def row(code, d0, excluded=""):
    return {"code": code, "list_date": d0, "excluded": excluded}


def test_matching_listing_date_passes_and_is_recorded():
    (r,) = build_sample.apply_listing_crosscheck([row("A", "20261015")], {"A": "20261015"})
    assert r["excluded"] == "" and r["list_dd"] == "20261015" and r["list_dd_check"] == "일치"


def test_reappearing_old_stock_is_excluded_as_a_suspected_false_listing():
    """거래정지 등으로 일별 데이터에서 빠졌다가 다시 나타난 종목은 LIST_DD 가 훨씬 이르다."""
    (r,) = build_sample.apply_listing_crosscheck([row("B", "20250601")], {"B": "20150312"})
    assert r["excluded"] == "재등장 의심(상장일 불일치)" and r["list_dd_check"] == "불일치"


def test_listing_date_later_than_first_appearance_is_also_flagged():
    (r,) = build_sample.apply_listing_crosscheck([row("C", "20250601")], {"C": "20250701"})
    assert r["excluded"] == "재등장 의심(상장일 불일치)"


def test_existing_exclusion_reason_is_kept():
    (r,) = build_sample.apply_listing_crosscheck([row("D", "20250601", "스팩·리츠")], {"D": "20150312"})
    assert r["excluded"] == "스팩·리츠" and r["list_dd_check"] == "불일치"


def test_stock_missing_from_the_snapshot_is_not_checked_not_excluded():
    """종목기본정보는 현재 상장 종목 스냅샷이라 상장폐지 종목은 없다 → 검증하지 못했을 뿐 제외하지 않는다."""
    (r,) = build_sample.apply_listing_crosscheck([row("E", "20250601")], {"A": "20261015"})
    assert r["excluded"] == "" and r["list_dd"] == "" and r["list_dd_check"] == "미실시"


def test_load_list_dd_maps_codes_and_fails_loudly_when_empty(monkeypatch):
    import krx_api
    import pytest
    monkeypatch.setattr(krx_api, "fetch", lambda service, d: [{"ISU_SRT_CD": "195990", "LIST_DD": "20261023"}])
    assert build_sample.load_list_dd("20261023") == {"195990": "20261023"}
    monkeypatch.setattr(krx_api, "fetch", lambda service, d: [])
    with pytest.raises(RuntimeError, match="비어"):
        build_sample.load_list_dd("20261023")


def test_detected_listings_returns_every_detected_row_with_its_exclusion(monkeypatch, tmp_path):
    """건강 점검과 과거 스냅샷 조회에는 제외 건뿐 아니라 탐지된 전체 목록(이름·상장일 포함)이 필요하다."""
    import config
    import test_logic
    for name in ("RAW", "MART", "META", "ROOT", "BUFFER_START", "SAMPLE_START"):
        monkeypatch.setattr(config, name, getattr(config, name))
    test_logic.setup(tmp_path)
    rows = {r["code"]: r for r in build_sample.detected_listings("20230106", "20230105")}
    assert set(rows) == {"A", "SP", "KNX1", "LU"}
    assert rows["A"]["excluded"] == "" and rows["A"]["list_date"] == "20230105" and rows["A"]["name"] == "엘리스테스트"
    assert rows["SP"]["excluded"] == "스팩·리츠" and rows["KNX1"]["excluded"] == "코넥스 이전상장"


def test_spac_is_excluded_by_name_or_by_the_spac_section():
    """'…호기업인수목적' 이름과 SECT_TP_NM 이 SPAC 인 종목은 '스팩'·'SPAC' 키워드가 없어도 제외한다 (2026-10-27 실측 사례)."""
    from collections import OrderedDict
    import test_logic

    def r(code, name, sect):
        return {**test_logic.row(code, name, 2000, 0), "SECT_TP_NM": sect}

    ksq = OrderedDict([("20230103", [test_logic.row("OLD", "기존", 1000, 0)]),
                       ("20230105", [test_logic.row("OLD", "기존", 1000, 0),
                                     r("S1", "에스케이증권제14호기업인수목적", "SPAC(소속부없음)"),
                                     r("S2", "이름은평범한회사", "SPAC(소속부없음)"),
                                     r("N1", "일반기업", "벤처기업부")])])
    rows = {x["code"]: x for x in build_sample.detect_listings(ksq, OrderedDict(), "20230105")}
    assert rows["S1"]["excluded"] == "스팩·리츠" and rows["S2"]["excluded"] == "스팩·리츠"
    assert rows["N1"]["excluded"] == ""


def test_new_columns_are_written_to_the_sample_csv():
    assert {"list_dd", "list_dd_check"} <= set(build_sample.COLUMNS)
