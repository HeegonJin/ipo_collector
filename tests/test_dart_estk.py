import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dart_estk  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures_real" / "estk_kmf_20261027.json"
# 실제 응답 발췌는 로컬 전용(.gitignore)이라 새로 클론하면 없다 → 실패가 아니라 건너뛴다
needs_fixture = pytest.mark.skipif(not FIXTURE.exists(), reason="tests/fixtures_real 은 로컬 전용(저장소에 없음)")


def test_parse_num_keeps_missing_as_none_not_zero():
    assert dart_estk.parse_num("15,000") == 15000.0
    assert dart_estk.parse_num("-") is None
    assert dart_estk.parse_num("") is None
    assert dart_estk.parse_num(None) is None
    assert dart_estk.parse_num("0") == 0.0


def test_parse_dates_korean_range():
    assert dart_estk.parse_dates("2026년 11월 24일 ~ 2026년 11월 25일") == ["20261124", "20261125"]
    assert dart_estk.parse_dates("2026년 11월 27일") == ["20261127"]
    assert dart_estk.parse_dates("-") == []


@needs_fixture
def test_estk_cache_refetches_only_when_newer_filing_appears(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "RAW", tmp_path)
    resp = json.loads(FIXTURE.read_text(encoding="utf-8"))
    calls = []
    monkeypatch.setattr(dart_estk, "fetch_estk", lambda corp, bgn, end: calls.append((bgn, end)) or resp)
    f1 = [{"rcept_no": "20261027000388", "rcept_dt": "20261027"}]
    dart_estk.estk_for_corp("01880139", f1)
    dart_estk.estk_for_corp("01880139", f1)
    assert calls == [("20261027", "20261027")]  # 최초 신고일 하루로 조회, 두 번째는 캐시
    f2 = f1 + [{"rcept_no": "20261105000100", "rcept_dt": "20261105"}]
    dart_estk.estk_for_corp("01880139", f2)
    assert len(calls) == 2 and calls[1] == ("20261027", "20261027")


@needs_fixture
def test_normalize_real_response():
    resp = json.loads(FIXTURE.read_text(encoding="utf-8"))
    (rec,) = dart_estk.normalize(resp)
    assert rec["rcept_no"] == "20261027000388" and rec["corp_code"] == "01880139"
    assert (rec["sub_start"], rec["sub_end"], rec["pay_date"]) == ("20261124", "20261125", "20261127")
    assert rec["offer_price"] == 15000.0 and rec["stock_cnt"] == 2_000_000
    assert rec["offer_amount"] == 30_000_000_000 and rec["sale_method"] == "일반공모"
    assert rec["old_share_cnt"] is None  # 구주매출 '-' 는 0 이 아니라 결측
