"""API 응답·인자에서 온 값(rcept_no, corp_code, 기준일)은 캐시 파일 경로에 쓰기 전에 형식을 검증한다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import dart_estk  # noqa: E402
import dart_terms  # noqa: E402
import krx_api  # noqa: E402
from core import ids  # noqa: E402

BAD = ["../x", "..\\x", "2026101200030", "202610120003088", "abc", "", "20261012000308/../../a", "２０２６１０１２０００３０８"]


@pytest.mark.parametrize("bad", BAD)
def test_rcept_no_must_be_14_ascii_digits(bad):
    with pytest.raises(ValueError):
        ids.safe_rcept_no(bad)


def test_valid_values_pass_through_unchanged():
    assert ids.safe_rcept_no("20261012000308") == "20261012000308"
    assert ids.safe_corp_code("00534729") == "00534729"
    assert ids.safe_date("20261023") == "20261023"


@pytest.mark.parametrize("bad", ["../../etc", "1234567", "123456789", "abcdefgh", ""])
def test_corp_code_must_be_8_ascii_digits(bad):
    with pytest.raises(ValueError):
        ids.safe_corp_code(bad)


@pytest.mark.parametrize("bad", ["2026-10-23", "../a", "202610", "20261323x"])
def test_date_must_be_yyyymmdd(bad):
    with pytest.raises(ValueError):
        ids.safe_date(bad)


@pytest.fixture(autouse=True)
def _tmp_raw(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RAW", tmp_path)


def test_document_cache_path_rejects_traversal_before_any_request(monkeypatch):
    monkeypatch.setattr(dart_terms.http, "safe_get", lambda *a, **k: pytest.fail("네트워크 호출이 일어나면 안 된다"))
    with pytest.raises(ValueError):
        dart_terms.fetch_document_xml("../../evil")


def test_estk_cache_path_rejects_traversal_before_any_request(monkeypatch):
    monkeypatch.setattr(dart_estk, "fetch_estk", lambda *a, **k: pytest.fail("네트워크 호출이 일어나면 안 된다"))
    with pytest.raises(ValueError):
        dart_estk.estk_for_corp("../../evil", [{"rcept_no": "20261012000308", "rcept_dt": "20261012"}])


def test_krx_cache_path_rejects_traversal_and_unknown_service():
    with pytest.raises(ValueError):
        krx_api.fetch("ksq_daily", "../../evil")
    with pytest.raises(ValueError):
        krx_api.fetch("../ksq_daily", "20261023")
