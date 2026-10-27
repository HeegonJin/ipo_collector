"""
발행조건확정 공시 원문(document.xml)에서 확정 공모가를 뽑는다.

estkRs.json 은 회사당 한 건만, 그것도 확정 전 값(희망가 최저)을 주므로 확정가의 근거로 쓸 수 없다 (2026-10-27 실측).
원문의 '공모개요' 표 한 줄을 읽는다:
  증권의 종류 | 증권 수량 | 액면가액 | 모집(매출)가액 | 모집(매출)총액 | 모집(매출)방법
  기명식 보통주 2,228,917 5,000 18,500 41,234,964,500 일반공모

실측으로 알게 된 것
  - 머리글 띄어쓰기가 문서마다 다르다 ('모집(매출)방법' / '모집(매출) 방법').
  - 정정 공시에는 표 앞에 '정정 전' / '정정 후' 표지가 붙는다. 정정 후 표만 쓴다. 정정 전만 있으면 확정으로 보지 않는다.
  - 본문에 '확정공모가액은 N원' 같은 문장이 있다. 표 값과 다르면 status=미확인 (조용히 확인으로 두지 않는다).
검산: 수량 × 가액 == 총액.
"""
import html
import io
import re
import zipfile

import requests

import config
from core.schema import Status

API = "https://opendart.fss.or.kr/api"
_ROW = re.compile(
    r"모집\(매출\)\s*방법\s*(?:기명식\s*)?보통주\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+(\S+)")
_BAND = re.compile(r"(?:공모희망가액|희망공모가액)[^\d]{0,40}([\d,]+)\s*원\s*~\s*([\d,]+)\s*원")
_SENT = re.compile(r"확정\s*공모가액(?:은|인|이)?\s*([\d,]+)\s*원|([\d,]+)\s*원으로\s*(?:최종\s*)?(?:확정|결정)")
_TAG = re.compile(r"정정\s*(전|후)")


def _n(s: str) -> float:
    return float(s.replace(",", ""))


def to_text(xml: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", xml)))


def _tagged_tables(text: str) -> list[tuple[str | None, tuple]]:
    out = []
    for m in _ROW.finditer(text):
        tags = _TAG.findall(text[max(0, m.start() - 220): m.start()])
        out.append((tags[-1] if tags else None, m.groups()))
    return out


def parse_offer_terms(text: str) -> dict:
    band = _BAND.search(text)
    sent = {_n(a or b) for a, b in _SENT.findall(text)}
    out = {"offer_price": None, "stock_cnt": None, "offer_amount": None, "sale_method": None,
           "band_low": _n(band.group(1)) if band else None, "band_high": _n(band.group(2)) if band else None,
           "sentence_prices": sorted(sent), "note": "", "status": Status.UNVERIFIED.value}
    tables = _tagged_tables(text)
    after = [g for tag, g in tables if tag == "후"]
    plain = [g for tag, g in tables if tag is None]
    chosen = after[-1] if after else (plain[-1] if plain else None)
    if chosen is None:
        out["note"] = "정정 후 표 없음" if tables else "공모개요 표 없음"
        return out
    cnt, _fv, price, total, method = chosen
    out.update(stock_cnt=_n(cnt), offer_price=_n(price), offer_amount=_n(total), sale_method=method)
    if abs(_n(cnt) * _n(price) - _n(total)) >= 1:
        out["note"] = "수량×가액≠총액"
    elif sent and _n(price) not in sent:
        out["note"] = f"표 {price} ≠ 본문 확정가 {sorted(sent)}"
    else:
        out["status"] = Status.CONFIRMED.value
    return out


def fetch_document_xml(rcept_no: str) -> str:
    path = config.RAW / "dart" / "doc" / f"{rcept_no}.xml"
    if path.exists():
        return path.read_text(encoding="utf-8")
    r = requests.get(f"{API}/document.xml", params={"crtfc_key": config.DART_API_KEY, "rcept_no": rcept_no}, timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"PK"):  # 오류는 zip 이 아니라 XML 메시지로 온다
        raise RuntimeError(f"DART document.xml 오류 ({rcept_no}): {r.text[:200]}")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    xml = z.read(z.namelist()[0]).decode("utf-8", errors="replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    return xml


def offer_terms_for(rcept_no: str) -> dict:
    return parse_offer_terms(to_text(fetch_document_xml(rcept_no)))


def final_offer_terms(rcept_nos: list[str]) -> dict:
    """발행조건확정 공시가 여러 건이면 접수번호가 가장 늦으면서 status=확인 인 것을 쓴다. 없으면 가장 늦은 결과."""
    results = [{**offer_terms_for(r), "rcept_no": r} for r in sorted(rcept_nos)]
    ok = [t for t in results if t["status"] == Status.CONFIRMED.value]
    return (ok or results)[-1]
