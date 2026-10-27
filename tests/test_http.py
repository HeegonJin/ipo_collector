"""공통 요청 함수: 오류 메시지에서 API 키를 가리고, 일시 오류만 재시도한다. 각 수집 모듈이 실제로 이 함수를 쓰는지도 확인."""
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import dart_api  # noqa: E402
import dart_estk  # noqa: E402
import dart_list  # noqa: E402
import dart_terms  # noqa: E402
from core import http  # noqa: E402

KEY = "SECRETKEY123"


class Resp:
    def __init__(self, status=200, url=f"https://opendart.fss.or.kr/api/x.json?crtfc_key={KEY}&a=1", body=None):
        self.status_code, self.url, self.reason, self._body = status, url, "Err", body or {}
        self.content, self.text = b"", ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error for url: {self.url}", response=self)

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DART_API_KEY", KEY)
    monkeypatch.setattr(config, "KRX_API_KEY", "KRXSECRET456")
    monkeypatch.setattr(config, "RAW", tmp_path)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)


def patch_get(monkeypatch, responses):
    calls = []
    it = iter(responses)

    def fake(url, **kw):
        calls.append(url)
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(http.requests, "get", fake)
    return calls


def test_http_error_message_hides_the_api_key(monkeypatch):
    patch_get(monkeypatch, [Resp(404)])
    with pytest.raises(requests.HTTPError) as e:
        http.safe_get("https://opendart.fss.or.kr/api/x.json", params={"crtfc_key": KEY})
    assert KEY not in str(e.value) and e.value.__cause__ is None and e.value.response.status_code == 404


def test_client_errors_are_not_retried(monkeypatch):
    calls = patch_get(monkeypatch, [Resp(401), Resp(200)])
    with pytest.raises(requests.HTTPError):
        http.safe_get("https://x", params={})
    assert len(calls) == 1


def test_server_errors_and_429_are_retried_then_succeed(monkeypatch):
    calls = patch_get(monkeypatch, [Resp(500), Resp(429), Resp(200, body={"ok": 1})])
    assert http.safe_get("https://x", params={}).json() == {"ok": 1}
    assert len(calls) == 3


def test_gives_up_after_the_attempt_limit_with_a_scrubbed_error(monkeypatch):
    calls = patch_get(monkeypatch, [Resp(503)] * 5)
    with pytest.raises(requests.HTTPError) as e:
        http.safe_get("https://x", params={}, attempts=3)
    assert len(calls) == 3 and KEY not in str(e.value)


def test_connection_errors_are_retried_and_scrubbed(monkeypatch):
    err = requests.ConnectionError(f"HTTPSConnectionPool: url=/api?crtfc_key={KEY} timed out")
    calls = patch_get(monkeypatch, [err, err, err])
    with pytest.raises(requests.ConnectionError) as e:
        http.safe_get("https://x", params={}, attempts=3)
    assert len(calls) == 3 and KEY not in str(e.value) and e.value.__cause__ is None


def test_both_configured_keys_are_scrubbed():
    assert http.scrub("a SECRETKEY123 b KRXSECRET456 c") == "a *** b *** c"


@pytest.mark.parametrize("call", [
    lambda: dart_list._fetch_range("20260101", "20260131"),
    lambda: dart_terms.fetch_document_xml("20260101000001"),
    lambda: dart_estk.fetch_estk("01234567", "20260101", "20260101"),
    lambda: dart_api._get("corpCode.xml"),
])
def test_every_dart_caller_goes_through_the_safe_path(monkeypatch, call):
    patch_get(monkeypatch, [Resp(500)] * 10)
    with pytest.raises(requests.HTTPError) as e:
        call()
    assert KEY not in str(e.value) and e.value.__cause__ is None
