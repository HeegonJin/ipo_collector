"""
DART 증권신고서 주요정보(estkRs.json, 지분증권)를 회사별로 받아 공시 버전(rcept_no)마다 한 줄로 정리한다.

원문 HTML 을 파싱하지 않고도 모집가액·청약일·납입일·주식 수·구주매출이 구조화되어 온다.
응답 그룹 (2026-10-27 실측): 일반사항 / 증권의종류 / 인수인정보 / 자금의사용목적 / 매출인에관한사항 / 일반청약자환매청구권

주의: 모집가액(slprc)이 '확정 공모가'인지는 접수 종류로 판단한다 (kind == 발행조건확정). 그 전 버전의 값은 희망가격 기반 예정값이다.
캐시: data/0_raw/dart/estk/<corp_code>.json — 목록에 새 rcept_no 가 생기면 다시 받는다.
"""
import json
import re
import time

import config
from core import http, ids

API ="https://opendart.fss.or.kr/api"
_DATE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def parse_num(v):
    """'15,000' → 15000.0. '-', '', None → None (결측을 0 으로 바꾸지 않는다)."""
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_dates(v):
    """'2026년 11월 24일 ~ 2026년 11월 25일' → ['20261124', '20261125']. 못 읽으면 []."""
    return [f"{y}{int(m):02d}{int(d):02d}" for y, m, d in _DATE.findall(v or "")]


def _group(resp: dict, title: str) -> list[dict]:
    for g in resp.get("group", []):
        if g.get("title") == title:
            return g.get("list", [])
    return []


def normalize(resp: dict) -> list[dict]:
    """estkRs 응답 → rcept_no 별 한 줄. 보통주 행을 우선하고 없으면 첫 행."""
    out = {}
    for row in _group(resp, "일반사항"):
        dates = parse_dates(row.get("sbd"))
        out[row["rcept_no"]] = {
            "rcept_no": row["rcept_no"], "corp_code": row["corp_code"], "corp_name": row["corp_name"],
            "sub_start": dates[0] if dates else None, "sub_end": dates[-1] if dates else None,
            "pay_date": (parse_dates(row.get("pymd")) or [None])[0],
        }
    by_rcept = {}
    for row in _group(resp, "증권의종류"):
        by_rcept.setdefault(row["rcept_no"], []).append(row)
    for rcept, rows in by_rcept.items():
        row = next((x for x in rows if x.get("stksen") == "보통주"), rows[0])
        rec = out.setdefault(rcept, {"rcept_no": rcept, "corp_code": row["corp_code"], "corp_name": row["corp_name"]})
        rec.update(stock_kind=row.get("stksen"), stock_cnt=parse_num(row.get("stkcnt")),
                   offer_price=parse_num(row.get("slprc")), offer_amount=parse_num(row.get("slta")),
                   sale_method=row.get("slmthn"))
    for row in _group(resp, "매출인에관한사항"):
        if row["rcept_no"] in out:
            out[row["rcept_no"]]["old_share_cnt"] = parse_num(row.get("slstk"))
    return list(out.values())


def fetch_estk(corp_code: str, bgn: str, end: str) -> dict:
    r = http.safe_get(f"{API}/estkRs.json", params={
        "crtfc_key": config.DART_API_KEY, "corp_code": corp_code, "bgn_de": bgn, "end_de": end})
    j = r.json()
    if j.get("status") not in ("000", "013"):
        raise RuntimeError(f"DART estkRs 오류 {j.get('status')} ({corp_code}): {j.get('message')}")
    time.sleep(0.2)
    return j


def estk_for_corp(corp_code: str, filings: list[dict]) -> list[dict]:
    """회사의 지분증권 신고서 목록(rcept_no, rcept_dt)을 받아 주요정보 한 건을 돌려준다.

    estkRs 는 '최초 신고일이 들어 있는 기간'으로만 응답하고 회사당 최신 정정본 한 건만 준다 (2026-10-27 실측).
    캐시는 받을 때의 최신 접수번호를 함께 저장해 두고, 그보다 새 공시가 생겼을 때만 다시 받는다."""
    corp_code = ids.safe_corp_code(corp_code)   # 캐시 파일 경로에 쓰기 전에 형식 검증
    first_dt = min(f["rcept_dt"] for f in filings)
    newest = max(f["rcept_no"] for f in filings)
    path = config.RAW / "dart" / "estk" / f"{corp_code}.json"
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("asof_max_rcept", "") >= newest:
            return normalize(cached["resp"])
    resp = fetch_estk(corp_code, first_dt, first_dt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"asof_max_rcept": newest, "resp": resp}, ensure_ascii=False), encoding="utf-8")
    return normalize(resp)
