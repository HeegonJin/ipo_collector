"""실제 KRX 응답을 녹화한 발췌(tests/fixtures_real)로 필드명·코드 형식 가정을 고정한다. (2026-10-27 녹화)"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_sample  # noqa: E402

FX = Path(__file__).parent / "fixtures_real"
# 실제 응답 발췌는 이용약관 확인 전이라 저장소에 올리지 않는다(.gitignore). 새로 클론하면 없으므로 실패가 아니라 건너뛴다.
pytestmark = pytest.mark.skipif(not (FX / "krx_ksq_daily_20261015.json").exists(),
                                reason="tests/fixtures_real 은 로컬 전용(저장소에 없음)")
DAILY_FIELDS = {"BAS_DD", "ISU_CD", "ISU_NM", "MKT_NM", "SECT_TP_NM", "TDD_CLSPRC", "CMPPREVDD_PRC", "FLUC_RT",
                "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "ACC_TRDVOL", "ACC_TRDVAL", "MKTCAP", "LIST_SHRS"}
BASE_FIELDS = {"ISU_CD", "ISU_SRT_CD", "ISU_NM", "ISU_ABBRV", "ISU_ENG_NM", "LIST_DD", "MKT_TP_NM", "SECUGRP_NM",
                "SECT_TP_NM", "KIND_STKCERT_TP_NM", "PARVAL", "LIST_SHRS"}


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def test_daily_fields_and_six_char_codes_with_letters():
    rows = load("krx_ksq_daily_20261015.json")
    assert all(set(r) == DAILY_FIELDS for r in rows)
    assert all(len(r["ISU_CD"]) == 6 for r in rows)          # ISIN 이 아니라 6자리 단축코드
    assert any(any(c.isalpha() for c in r["ISU_CD"]) for r in rows)
    assert all("ISU_SRT_CD" not in r for r in rows)            # 일별 응답에는 ISU_SRT_CD 가 없다
    assert all(build_sample.short_code(r) == r["ISU_CD"] for r in rows)


def test_knx_daily_has_same_fields():
    assert all(set(r) == DAILY_FIELDS for r in load("krx_knx_daily_20261023.json"))


def test_base_info_has_listing_date_and_spac_marker():
    rows = load("krx_ksq_base_20261023.json")
    assert all(set(r) == BASE_FIELDS for r in rows)
    by = {r["ISU_NM"]: r for r in rows}
    assert by["진코스텍"]["LIST_DD"] == "20261015" and by["디티에스"]["LIST_DD"] == "20261023"
    assert by["엔에이치기업인수목적34호"]["SECT_TP_NM"].startswith("SPAC")


def test_back_calculated_offer_matches_dart_except_known_case():
    """KRX 종가 − 전일대비 = 상장일 기준가. 멜콘은 DART 확정 공모가와 일치(12,300)하고,
    진코스텍은 KRX 23,850 vs DART 증권발행실적보고서 23,500 으로 다르다 → 공모가 주 출처는 DART."""
    by = {r["ISU_NM"]: r for r in load("krx_ksq_daily_20261015.json")}
    est = lambda r: build_sample.num(r["TDD_CLSPRC"]) - build_sample.num(r["CMPPREVDD_PRC"])
    assert est(by["멜콘"]) == 12300
    assert est(by["진코스텍"]) == 23850 != 23500
