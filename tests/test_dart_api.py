"""DART 회사코드 매핑(corpCode.xml) 캐시: 처음 한 번만 받되, 필요하면 새로 받을 수 있어야 한다.
캐시 이후에 상장한 종목은 매핑에 없어서 DART 와 연결되지 않기 때문이다 (2026-10-29 상장 티앤이코리아 사례)."""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import dart_api  # noqa: E402


def zip_of(*pairs):
    items = "".join(f"<list><corp_code>{c}</corp_code><stock_code>{s}</stock_code></list>" for s, c in pairs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", f"<result>{items}</result>")
    return buf.getvalue()


class Resp:
    def __init__(self, content):
        self.content = content


def setup(monkeypatch, tmp_path, *versions):
    monkeypatch.setattr(config, "RAW", tmp_path)
    calls = []
    it = iter(versions)
    monkeypatch.setattr(dart_api, "_get", lambda path, **kw: calls.append(path) or Resp(next(it)))
    return calls


def test_map_is_downloaded_once_and_then_read_from_the_cache(monkeypatch, tmp_path):
    calls = setup(monkeypatch, tmp_path, zip_of(("195990", "00534729")))
    assert dart_api.corp_code_map() == {"195990": "00534729"}
    assert dart_api.corp_code_map() == {"195990": "00534729"}
    assert calls == ["corpCode.xml"]


def test_refresh_downloads_again_and_picks_up_newly_listed_stocks(monkeypatch, tmp_path):
    calls = setup(monkeypatch, tmp_path, zip_of(("195990", "00534729")),
                  zip_of(("195990", "00534729"), ("0053F0", "01999999")))
    assert "0053F0" not in dart_api.corp_code_map()
    assert dart_api.corp_code_map(refresh=True)["0053F0"] == "01999999"
    assert dart_api.corp_code_map()["0053F0"] == "01999999"        # 새로 받은 값이 캐시로 저장된다
    assert len(calls) == 2
