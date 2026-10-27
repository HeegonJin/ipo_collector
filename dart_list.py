"""
DART 발행공시(C) 목록을 기간 단위로 받아 지분증권 신고서만 거른다.

검증된 사실 (2026-10-27 실측)
  - list.json 의 pblntf_detail_ty 는 서버가 무시한다 (C001~C010 모두 같은 건수). report_nm 으로 직접 거른다.
  - 응답에 pblntf_detail_ty 필드가 없다. 필드: corp_cls corp_code corp_name flr_nm rcept_dt rcept_no report_nm rm stock_code
  - 접수 구분은 report_nm 접두사: [기재정정] [첨부정정] [발행조건확정] (접두사 없음 = 최초)

캐시: data/0_raw/dart/list/YYYYMM.json. 끝난 달만 캐시하고, 진행 중인 달은 매번 다시 받는다.
"""
import json
import re
import time
from datetime import date, datetime

import config
from core import http

API ="https://opendart.fss.or.kr/api"
EQUITY_KEYWORD = "증권신고서(지분증권)"
_PREFIX = re.compile(r"^\[([^\]]+)\]")
KIND_BY_PREFIX = {"기재정정": "기재정정", "첨부정정": "첨부정정", "발행조건확정": "발행조건확정"}


def report_kind(report_nm: str) -> str:
    m = _PREFIX.match(report_nm.strip())
    if not m:
        return "최초"
    return KIND_BY_PREFIX.get(m.group(1), "기타:" + m.group(1))


def is_equity_registration(row: dict) -> bool:
    return EQUITY_KEYWORD in row.get("report_nm", "")


def is_spac(row: dict) -> bool:
    name = row.get("corp_name", "")
    return any(k in name for k in config.EXCLUDE_NAME_KEYWORDS) or "기업인수목적" in name


def _fetch_range(bgn: str, end: str) -> list[dict]:
    rows, page = [], 1
    while True:
        r = http.safe_get(f"{API}/list.json", params={
            "crtfc_key": config.DART_API_KEY, "bgn_de": bgn, "end_de": end,
            "pblntf_ty": "C", "page_count": 100, "page_no": page})
        j = r.json()
        if j.get("status") == "013":  # 조회된 데이터 없음
            return rows
        if j.get("status") != "000":
            raise RuntimeError(f"DART list.json 오류 {j.get('status')}: {j.get('message')}")
        rows += j.get("list", [])
        if page >= int(j.get("total_page", 1)):
            return rows
        page += 1
        time.sleep(0.2)


def month_ranges(start: str, end: str):
    """YYYYMMDD 두 날짜 사이의 (YYYYMM, 시작일, 끝일) 목록."""
    s = datetime.strptime(start, "%Y%m%d").date()
    e = datetime.strptime(end, "%Y%m%d").date()
    d = s.replace(day=1)
    while d <= e:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        last = date.fromordinal(nxt.toordinal() - 1)
        yield d.strftime("%Y%m"), max(d, s).strftime("%Y%m%d"), min(last, e).strftime("%Y%m%d")
        d = nxt


def filings_for_month(yyyymm: str, bgn: str, end: str, today: date | None = None) -> list[dict]:
    today = today or date.today()
    path = config.RAW / "dart" / "list" / f"{yyyymm}.json"
    end_d = datetime.strptime(end, "%Y%m%d").date()
    next_month = date(end_d.year + (end_d.month == 12), end_d.month % 12 + 1, 1)
    last_day = date.fromordinal(next_month.toordinal() - 1)
    # 끝난 달이고 1일~말일 전체를 받았을 때만 캐시한다 (중순까지만 받은 부분 달이 완성본으로 굳으면 공시가 조용히 빠진다)
    cacheable = end_d < today.replace(day=1) and bgn.endswith("01") and end_d == last_day
    if path.exists() and cacheable:
        return json.loads(path.read_text(encoding="utf-8"))
    rows = _fetch_range(bgn, end)
    if cacheable:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def equity_registrations(start: str, end: str) -> list[dict]:
    """기간 내 지분증권 신고서 (스팩 제외). 각 행에 kind 를 붙인다. rcept_no 중복은 한 번만."""
    seen, out = set(), []
    for yyyymm, bgn, last in month_ranges(start, end):
        for r in filings_for_month(yyyymm, bgn, last):
            if not is_equity_registration(r) or is_spac(r) or r["rcept_no"] in seen:
                continue
            seen.add(r["rcept_no"])
            out.append({**r, "kind": report_kind(r["report_nm"])})
    out.sort(key=lambda r: (r["rcept_dt"], r["rcept_no"]))
    return out


RESULT_KEYWORD = "증권발행실적보고서"


def result_reports(start: str, end: str) -> dict:
    """기간 내 증권발행실적보고서를 회사코드별로 접수일 순으로 묶는다. rcept_no 중복은 한 번만."""
    seen, out = set(), {}
    for yyyymm, bgn, last in month_ranges(start, end):
        for r in filings_for_month(yyyymm, bgn, last):
            if RESULT_KEYWORD in r.get("report_nm", "") and r["rcept_no"] not in seen:
                seen.add(r["rcept_no"])
                out.setdefault(r["corp_code"], []).append(r)
    for rows in out.values():
        rows.sort(key=lambda r: (r["rcept_dt"], r["rcept_no"]))
    return out


def pick_result_report(reports: list[dict], after_dt: str):
    """확정 공시 접수일(after_dt) 이후 가장 먼저 접수된 실적보고서. 없으면 None."""
    return next((r for r in reports if r["rcept_dt"] >= after_dt), None)


if __name__ == "__main__":
    import sys
    start = sys.argv[1] if len(sys.argv) > 1 else config.BUFFER_START
    end = sys.argv[2] if len(sys.argv) > 2 else date.today().strftime("%Y%m%d")
    regs = equity_registrations(start, end)
    print(f"[DART] 지분증권 신고서 {len(regs)}건, 회사 {len({r['corp_code'] for r in regs})}곳 ({start}~{end})")
