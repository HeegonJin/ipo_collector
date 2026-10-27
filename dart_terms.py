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

import config
from core import http, ids
from core.schema import Status

API = "https://opendart.fss.or.kr/api"
_KIND = r"(보통주|[가-힣]{0,10}우선주|[가-힣]{0,10}종류주식)"
_HEADER = re.compile(r"모집\(매출\)\s*방법\s*")
# 종류 | 수량 | 액면가 | 모집(매출)가액 | 모집(매출)총액 | 방법  (표 머리글 바로 뒤에 이어지는 행들)
_NUM = r"([\d,]+)\s*(?:주|원)?"   # 셀에 단위가 붙은 문서가 있다 ('3,000,000주', '9,200원')
_ROW = re.compile(rf"(?:(?:기명식|무기명식)\s*)?{_KIND}\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+(\S+)\s*")
# 정정사항 요약에 적히는 확정 값: '모집(매출)확정가액: 14,000원', '모집(매출) 확정총액: 16,800,000,000원'
_CONF_PRICE = re.compile(r"모집\(매출\)\s*확정가액\s*[:：]?\s*([\d,]+)\s*원")
_CONF_TOTAL = re.compile(r"모집\(매출\)\s*확정총액\s*[:：]?\s*([\d,]+)\s*원")
_BAND = re.compile(r"(?:공모희망가액|희망공모가액)[^\d]{0,40}([\d,]+)\s*원\s*~\s*([\d,]+)\s*원")
_SENT = re.compile(r"확정\s*공모가액(?:은|인|이)?\s*([\d,]+)\s*원|([\d,]+)\s*원으로\s*(?:최종\s*)?(?:확정|결정)")
_TAG = re.compile(r"정정\s*(전|후)")


def _n(s: str) -> float:
    return float(s.replace(",", ""))


def to_text(xml: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", xml)))


def _tagged_tables(text: str) -> list[tuple[str | None, list[tuple]]]:
    """공모개요 표들. 각 표는 ('전'|'후'|None, [행 튜플...]). 머리글 바로 뒤에 이어지는 행만 그 표의 행으로 본다."""
    out = []
    for h in _HEADER.finditer(text):
        pos, rows = h.end(), []
        while (m := _ROW.match(text, pos)):
            rows.append(m.groups())
            pos = m.end()
        if rows:
            tags = _TAG.findall(text[max(0, h.start() - 220): h.start()])
            out.append((tags[-1] if tags else None, rows))
    return out


def _pick_row(rows: list[tuple]) -> tuple:
    """한 표에 종류가 여럿이면 보통주 행을 우선한다."""
    return next((r for r in rows if r[0] == "보통주"), rows[0])


def parse_offer_terms(text: str) -> dict:
    band = _BAND.search(text)
    sent = {_n(a or b) for a, b in _SENT.findall(text)}
    out = {"offer_price": None, "stock_kind": None, "stock_cnt": None, "offer_amount": None, "sale_method": None,
           "band_low": _n(band.group(1)) if band else None, "band_high": _n(band.group(2)) if band else None,
           "sentence_prices": sorted(sent), "note": "", "status": Status.UNVERIFIED.value}
    field = _confirmed_field(text)
    tables = _tagged_tables(text)
    after = [g for tag, g in tables if tag == "후"]
    plain = [g for tag, g in tables if tag is None]
    chosen = after[-1] if after else (plain[-1] if plain else None)
    table_ok = False
    if chosen is not None:
        kind, cnt, _fv, price, total, method = _pick_row(chosen)
        out.update(stock_kind=kind, stock_cnt=_n(cnt), offer_price=_n(price), offer_amount=_n(total),
                   sale_method=method, source="table")
        table_ok = abs(_n(cnt) * _n(price) - _n(total)) < 1
        if not table_ok:
            out["note"] = "수량×가액≠총액"
    if field and not table_ok:      # 표가 없거나 검산이 안 되면 원문이 명시한 확정 값을 쓴다
        out.update(offer_price=field["price"], offer_amount=field["total"], stock_cnt=field["cnt"], source="field",
                   note="")
        if chosen is None:
            out["sale_method"] = None
        return _finish(out, sent, field)
    if chosen is None:
        out["note"] = "정정 후 표 없음" if tables else "공모개요 표 없음"
        return out
    return _finish(out, sent, field) if table_ok else out


def _confirmed_field(text: str):
    """'확정가액'·'확정총액' 필드. 총액이 가액으로 정확히 나뉠 때만 인정한다 (주식 수 = 총액 / 가액)."""
    p, t = _CONF_PRICE.search(text), _CONF_TOTAL.search(text)
    if not (p and t):
        return None
    price, total = _n(p.group(1)), _n(t.group(1))
    if price <= 0 or total % price != 0:
        return None
    return {"price": price, "total": total, "cnt": total / price}


def _finish(out: dict, sent: set, field) -> dict:
    """본문 문장·확정 필드와 대조해 상태를 정한다. 값이 서로 다르면 확인으로 두지 않는다."""
    price = out["offer_price"]
    if field and out["source"] == "table" and field["price"] != price:
        out["note"] = f"표 {int(price)} ≠ 확정가액 필드 {int(field['price'])}"
    elif sent and price not in sent:
        out["note"] = f"{out['source']} {int(price)} ≠ 본문 확정가 {sorted(int(s) for s in sent)}"
    else:
        out["status"] = Status.CONFIRMED.value
    return out


def fetch_document_xml(rcept_no: str) -> str:
    rcept_no = ids.safe_rcept_no(rcept_no)   # 캐시 파일 경로에 쓰기 전에 형식 검증
    path = config.RAW / "dart" / "doc" / f"{rcept_no}.xml"
    if path.exists():
        return path.read_text(encoding="utf-8")
    r = http.safe_get(f"{API}/document.xml", params={"crtfc_key": config.DART_API_KEY, "rcept_no": rcept_no}, timeout=60)
    if not r.content.startswith(b"PK"):  # 오류는 zip 이 아니라 XML 메시지로 온다
        raise RuntimeError(http.scrub(f"DART document.xml 오류 ({rcept_no}): {r.text[:200]}"))
    z = zipfile.ZipFile(io.BytesIO(r.content))
    xml = z.read(z.namelist()[0]).decode("utf-8", errors="replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    return xml


def offer_terms_for(rcept_no: str) -> dict:
    return parse_offer_terms(to_text(fetch_document_xml(rcept_no)))


_RESULT_ROW = re.compile(rf"모집\s+(?:(?:기명식|무기명식)\s*)?{_KIND}\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)")


def parse_result_report(text: str) -> dict:
    """증권발행실적보고서의 '자금조달 내용' 표: 신고서상발행예정총액 | 발행가액 | 수량 | 발행총액.
    발행가액은 실제로 청약·납입된 가격이라 발행조건확정 공시의 '예정' 표기보다 믿을 수 있다 (진코스텍 사례)."""
    out = {"issue_price": None, "stock_cnt": None, "issue_amount": None, "status": Status.UNVERIFIED.value}
    rows = _RESULT_ROW.findall(text)
    if not rows:
        return out
    ok = [r for r in rows if abs(_n(r[2]) * _n(r[3]) - _n(r[4])) < 1]
    pool = ok or rows
    _kind, _planned, price, cnt, amount = next((r for r in pool if r[0] == "보통주"), pool[0])
    out.update(issue_price=_n(price), stock_cnt=_n(cnt), issue_amount=_n(amount))
    if ok:
        out["status"] = Status.CONFIRMED.value
    return out


def reconcile(final: dict, result: dict | None) -> dict:
    """확정 공시 값과 실적보고서 발행가액(실제 발행가, 수량×가액=총액 검산 통과분만)을 대조한다.
    일치하면 확인으로 올리고, 다르면 미확인으로 내리며 두 값을 메모에 남긴다. 확정 공시에서 가격을 못 읽었으면
    실적보고서 값을 단독 채택한다. 실적보고서가 없거나 읽지 못하면 '미실시'로 두고 상태는 그대로 둔다."""
    out = {**final, "crosscheck": "미실시"}
    if not result or result.get("issue_price") is None or result.get("status") != Status.CONFIRMED.value:
        return out
    if final.get("offer_price") is None:   # 확정 공시에서 가격을 못 읽었다 → 실적보고서 값을 단독 채택
        out.update(offer_price=result["issue_price"], status=Status.CONFIRMED.value, crosscheck="실적보고서 단독",
                   rcept_no=result.get("rcept_no", ""), available_dt=result.get("rcept_dt"),
                   note="확정 공시 표를 읽지 못해 실적보고서 발행가액 사용")
        return out
    if final["offer_price"] == result["issue_price"]:   # 독립된 두 출처가 일치하면 확인으로 올린다
        out.update(crosscheck="일치", status=Status.CONFIRMED.value)
        return out
    out.update(crosscheck="불일치", status=Status.UNVERIFIED.value,
               note=f"실적보고서 {int(result['issue_price'])} ≠ 확정공시 {int(final['offer_price'])}")
    return out


def result_report_terms(rcept_no: str) -> dict:
    return parse_result_report(to_text(fetch_document_xml(rcept_no)))


def final_offer_terms(rcept_nos: list[str]) -> dict:
    """발행조건확정 공시가 여러 건이면 접수번호가 가장 늦으면서 status=확인 인 것을 쓴다. 없으면 가장 늦은 결과."""
    results = [{**offer_terms_for(r), "rcept_no": r} for r in sorted(rcept_nos)]
    ok = [t for t in results if t["status"] == Status.CONFIRMED.value]
    return (ok or results)[-1]
