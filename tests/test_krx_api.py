import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import krx_api  # noqa: E402


class FakeResp:
    def __init__(self, status=200, rows=None):
        self.status_code, self._rows = status, rows or []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return {"OutBlock_1": self._rows}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RAW", tmp_path / "0_raw")
    monkeypatch.setattr(config, "META", tmp_path / "_meta")
    monkeypatch.setattr(config, "KRX_API_KEY", "test-key")
    monkeypatch.setattr(krx_api.time, "sleep", lambda s: None)
    return tmp_path


def fmt(d):
    return d.strftime("%Y%m%d")


def test_empty_response_for_recent_date_is_not_cached(env, monkeypatch):
    monkeypatch.setattr(krx_api.requests, "get", lambda *a, **k: FakeResp(rows=[]))
    recent = fmt(date.today() - timedelta(days=1))
    assert krx_api.fetch("ksq_daily", recent) == []
    assert not krx_api._cache_path("ksq_daily", recent).exists()


def test_empty_response_for_old_date_is_cached_as_holiday(env, monkeypatch):
    monkeypatch.setattr(krx_api.requests, "get", lambda *a, **k: FakeResp(rows=[]))
    assert krx_api.fetch("ksq_daily", "20230102") == []
    assert krx_api._cache_path("ksq_daily", "20230102").exists()


def test_cached_date_is_not_refetched(env, monkeypatch):
    calls = []
    monkeypatch.setattr(krx_api.requests, "get", lambda *a, **k: calls.append(1) or FakeResp(rows=[{"ISU_CD": "0158S0"}]))
    krx_api.fetch("ksq_daily", "20230103")
    krx_api.fetch("ksq_daily", "20230103")
    assert len(calls) == 1


def test_collect_skips_unapproved_index_but_keeps_trading_days(env, monkeypatch):
    def fake_get(url, **k):
        if "kosdaq_dd_trd" in url:
            return FakeResp(status=401)
        weekday = k["params"]["basDd"] in ("20230103", "20230104")
        return FakeResp(rows=[{"ISU_CD": "0158S0"}] if weekday else [])

    monkeypatch.setattr(krx_api.requests, "get", fake_get)
    assert krx_api.collect("20230102", "20230104") == ["20230103", "20230104"]
