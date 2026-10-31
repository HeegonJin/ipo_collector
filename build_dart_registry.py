"""
DART 지분증권 신고서 → ipo_registry 후보 + 공시 버전별 공모 조건.

  python build_dart_registry.py 20230101 20261027 [KRX 종목기본정보 기준일]

출력 (data/2_mart)
  dart_ipo_registry.csv : 회사당 한 줄. ipo_id = {corp_code}_{최초 증권신고서 rcept_no}
  dart_offer_terms.csv  : 공시 버전(rcept_no)당 한 줄. available_at = 접수일 23:59:59 KST (목록 API 가 날짜만 주므로 보수적으로)

공모가
  - 확정 공모가: 발행조건확정 공시 원문 표에서 읽는다 (dart_terms.final_offer_terms). 검산·본문 문장과 맞을 때만 status=확인.
  - estkRs 값은 확정 전 예정값(희망가 최저)이라 offer_price_expected 에만 둔다.
IPO 후보
  - is_ipo_candidate: 최초 신고서의 모집 방법이 '일반공모' (상장사의 일반공모 유상증자도 여기에 걸릴 수 있다)
  - in_trading_universe: KRX 코스닥 종목기본정보의 상장일(LIST_DD)이 최초 신고일 ~ +400일 안에 있음.
    기준일 스냅샷에 없는 종목(상장폐지·코스피·미상장)은 False. 상장폐지 종목이 빠지는 생존자 편향은 KRX 일별 데이터 단계에서 보완한다.
"""
import csv
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import config
import dart_api
import dart_estk
import dart_list
import dart_terms
import krx_api
from core import settings
from core.ids import make_ipo_id
from core.schema import Status

REGISTRY_COLS = ["ipo_id", "corp_code", "stock_code", "corp_name", "first_rcept_no", "first_rcept_dt", "sale_method",
                 "is_ipo_candidate", "list_dd", "list_dd_source", "in_trading_universe", "pre_sample", "universe_note", "last_seen",
                 "delisted_after_listing", "n_filings", "last_kind",
                 "offer_price_final", "offer_price_status", "offer_price_crosscheck", "offer_price_rcept",
                 "offer_price_available_dt", "band_low", "band_high", "offer_price_note"]
TERMS_COLS = ["ipo_id", "rcept_no", "rcept_dt", "kind", "available_at", "offer_price", "offer_price_status",
              "offer_price_expected", "stock_cnt", "old_share_cnt", "offer_amount", "sub_start", "sub_end",
              "pay_date", "sale_method"]
LISTING_WINDOW_DAYS = 400


def available_at(rcept_dt: str) -> str:
    return f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:]}T23:59:59+09:00"


def listed_within_window(first_rcept_dt: str, list_dd: str | None) -> bool:
    if not list_dd:
        return False
    first = datetime.strptime(first_rcept_dt, "%Y%m%d").date()
    listed = datetime.strptime(list_dd, "%Y%m%d").date()
    return first <= listed <= first + timedelta(days=LISTING_WINDOW_DAYS)


def _history_list_dd(code: str, d0: str) -> str | None:
    """상장일(d0) 시점의 종목기본정보 스냅샷에서 LIST_DD. 오늘 스냅샷에 없는 종목(이후 상장폐지)을 위해 쓴다."""
    for x in krx_api.fetch("ksq_base", d0):
        if x["ISU_SRT_CD"] == code:
            return x["LIST_DD"]
    return None


def krx_listing_dates(base_date: str, detected: dict | None = None) -> dict:
    """corp_code → (stock_code, LIST_DD, 출처). 출처는 '현재'(base_date 스냅샷) 또는 '과거 스냅샷'.

    detected 는 KRX 일별 데이터로 찾은 신규상장 {종목코드: 상장일}. 오늘의 종목기본정보에는 이미 상장폐지된 종목이 없어서
    그대로 쓰면 폐지된 IPO 가 매매 대상에서 조용히 빠진다 → 현재 스냅샷에 없는 종목만 상장일 시점의 스냅샷에서 찾는다.
    DART 회사코드 매핑(corpCode.xml)은 폐지 종목도 포함한다 (2026-10-27 실측)."""
    # 못 받거나 비어 있으면 매매 대상이 조용히 0건이 되므로 경고로 넘기지 않고 실패시킨다.
    try:
        rows = krx_api.fetch("ksq_base", base_date)
    except Exception as e:
        raise RuntimeError(f"KRX ksq_base({base_date}) 종목기본정보를 받지 못함: {type(e).__name__}: {e}") from e
    if not rows:
        raise RuntimeError(f"KRX ksq_base({base_date}) 응답이 비어 있음 — 기준일이 휴장일이거나 서비스 미승인일 수 있다")
    base = {x["ISU_SRT_CD"]: (x["LIST_DD"], "현재") for x in rows}
    for code, d0 in (detected or {}).items():
        if code not in base and (dd := _history_list_dd(code, d0)):
            base[code] = (dd, "과거 스냅샷")
    corp_map = dart_api.corp_code_map()
    if any(code not in corp_map for code in (detected or {})):
        corp_map = dart_api.corp_code_map(refresh=True)   # 캐시 이후에 상장한 종목은 매핑에 없다 → 한 번 새로 받는다
    return {corp: (stock, *base[stock]) for stock, corp in corp_map.items() if stock in base}


def universe_gaps(detected_rows: list[dict], registry: list[dict], last_seen: dict, last_day: str | None,
                  mapped: set | None = None) -> list[dict]:
    """KRX 가 신규상장으로 탐지했지만 매매 대상에 없는 종목과 그 사유 (합병·이전상장 / 신고서 없음 / 상장폐지 의심).
    이미 제외 사유가 있는 종목(스팩·코넥스 이전)은 제외 목록이 따로 있으므로 넣지 않는다."""
    by_stock = {r["stock_code"]: r for r in registry if r["stock_code"]}
    out = []
    for d in detected_rows:
        r = by_stock.get(d["code"])
        if d["excluded"] or (r and r["in_trading_universe"]):
            continue
        if r:
            reason = r["universe_note"]
        elif mapped is not None and d["code"] not in mapped:
            reason = "DART 회사코드 매핑 없음(상장 직후라 아직 DART 목록에 없을 수 있음)"
        else:
            reason = "지분증권 신고서 없음(합병·이전상장 등)"
        if last_day and last_seen.get(d["code"], last_day) < last_day:
            reason = "상장폐지 의심: " + reason
        out.append({"name": d["name"], "code": d["code"], "list_date": d["list_date"], "reason": reason})
    return out


def _final_price(filings: list[dict], universe: bool, corp_reports: list[dict], list_dd: str) -> dict:
    """확정 공모가: 발행조건확정 공시 원문 → 증권발행실적보고서 발행가액과 대조. 원문은 매매 대상 후보에만 내려받는다.

    상장 뒤(rcept_dt > 상장일)의 공시는 유상증자 등 다른 공모라서 IPO 확정가 후보에서 뺀다.
    모집 방법이 '일반공모'가 아니면(주주배정 등) IPO 가격으로 믿지 않는다."""
    final = {"offer_price": None, "status": Status.UNVERIFIED.value, "rcept_no": "", "band_low": None,
             "band_high": None, "note": "발행조건확정 공시 없음", "crosscheck": "미실시", "available_dt": None}
    if not universe:
        has = any(f["kind"] == "발행조건확정" for f in filings)
        return {**final, "note": "매매 대상 아님: 원문 미조회"} if has else final
    pre = [f for f in filings if f["rcept_dt"] <= list_dd]   # IPO 기간의 공시
    confirmed = [f["rcept_no"] for f in pre if f["kind"] == "발행조건확정"]
    final_dt = pre[0]["rcept_dt"]
    if confirmed:
        final = {**dart_terms.final_offer_terms(confirmed), "crosscheck": "미실시"}
        final_dt = next(f["rcept_dt"] for f in pre if f["rcept_no"] == final["rcept_no"])
        final["available_dt"] = final_dt
        method = final.get("sale_method")
        if method and not method.startswith("일반공모"):
            return {**final, "status": Status.UNVERIFIED.value, "note": f"모집 방법이 일반공모가 아님({method}) — IPO 가격으로 보지 않음"}
    report = dart_list.pick_result_report([r for r in corp_reports if r["rcept_dt"] <= list_dd], final_dt)
    result = None
    if report:
        result = {**dart_terms.result_report_terms(report["rcept_no"]), "rcept_no": report["rcept_no"],
                  "rcept_dt": report["rcept_dt"]}
    return dart_terms.reconcile(final, result)


PRE_SAMPLE_NOTE = "표본 시작일 이전 상장"


def is_pre_sample(note: str, list_dd: str, buffer_start: str) -> bool:
    """표본 시작일(2023-07-01) 전, 일별 시세가 있는 구간(buffer_start 이후)에 상장한 종목. 참고용으로 데이터에는 넣되
    매매 대상(in_trading_universe)이 아니어서 학습·검증·모의 운영 어디에도 섞이지 않는다."""
    return note == PRE_SAMPLE_NOTE and list_dd >= buffer_start


def universe_decision(last_pre_listing_dt: str | None, list_dd: str, sample_start: str, exclude_reason: str | None):
    """매매 대상 여부와 이유. last_pre_listing_dt 는 상장일 이전 마지막 지분증권 신고일(없으면 None).
    표본 시작일 이전 상장, 코넥스 이전상장(D11)은 제외한다. 상장 전 신고가 없으면(합병·이전상장 등 공모 없는 상장,
    또는 상장 후 유상증자만 있는 기존 상장사) 제외한다. 최초 신고가 철회돼 오래전이어도 마지막 신고가 가까우면 포함한다."""
    if exclude_reason:
        return False, exclude_reason
    if not list_dd:
        return False, "KRX 상장일 없음"
    if not last_pre_listing_dt:
        return False, "상장 전 지분증권 신고서 없음(합병·이전상장 등 공모 없는 상장 또는 기존 상장사)"
    if not listed_within_window(last_pre_listing_dt, list_dd):
        return False, "상장 전 마지막 신고가 400일 초과"
    if list_dd < sample_start:
        return False, PRE_SAMPLE_NOTE
    return True, ""


def _registry_row(ipo_id, corp, filings, estk, listing, final, universe, note="", seen=("", False), pre_sample=False) -> dict:
    first = filings[0]
    sale_method = next((x.get("sale_method") for x in estk.values() if x.get("sale_method")), "")
    stock, list_dd, *src = listing
    last_seen, delisted = seen
    return {
        "ipo_id": ipo_id, "corp_code": corp, "stock_code": stock, "corp_name": first["corp_name"],
        "first_rcept_no": first["rcept_no"], "first_rcept_dt": first["rcept_dt"], "sale_method": sale_method,
        "is_ipo_candidate": sale_method == "일반공모", "list_dd": list_dd, "list_dd_source": src[0] if src else "",
        "in_trading_universe": universe, "pre_sample": pre_sample, "universe_note": note, "last_seen": last_seen,
        "delisted_after_listing": delisted, "n_filings": len(filings), "last_kind": filings[-1]["kind"],
        "offer_price_final": final["offer_price"], "offer_price_status": final["status"],
        "offer_price_crosscheck": final.get("crosscheck", "미실시"),
        "offer_price_rcept": final.get("rcept_no", ""), "offer_price_available_dt": final.get("available_dt"),
        "band_low": final.get("band_low"),
        "band_high": final.get("band_high"), "offer_price_note": final.get("note", ""),
    }


def _terms_rows(ipo_id, filings, estk, final) -> list[dict]:
    rows = []
    for f in filings:
        t = estk.get(f["rcept_no"], {})
        is_final = f["rcept_no"] == final.get("rcept_no")
        rows.append({
            "ipo_id": ipo_id, "rcept_no": f["rcept_no"], "rcept_dt": f["rcept_dt"], "kind": f["kind"],
            "available_at": available_at(f["rcept_dt"]),
            "offer_price": final["offer_price"] if is_final else None,
            "offer_price_status": final["status"] if is_final else Status.UNVERIFIED.value,
            "offer_price_expected": t.get("offer_price"),
            **{k: t.get(k) for k in ("stock_cnt", "old_share_cnt", "offer_amount", "sub_start", "sub_end",
                                     "pay_date", "sale_method")},
        })
    return rows


def build(start: str, end: str, base_date: str, exclude: dict | None = None, sample_start: str | None = None,
          detected: dict | None = None, last_seen: dict | None = None, last_day: str | None = None):
    """exclude: {종목코드: 사유} — KRX 일별 데이터로 찾은 코넥스 이전상장 등 (build_sample.detected_listings).
    sample_start: 이 날짜 이전 상장은 매매 대상이 아니다 (기본은 config/universe_v1.yaml).
    detected: {종목코드: 상장일} KRX 탐지 신규상장 — 상장폐지된 종목의 상장일을 과거 스냅샷에서 찾는 데 쓴다.
    last_seen/last_day: 일별 데이터 마지막 등장일 — 상장 뒤 사라진 종목(delisted_after_listing)을 표시한다."""
    sample_start = sample_start or settings.load_universe()["sample_start"].replace("-", "")
    buffer_start = settings.load_universe()["buffer_start"].replace("-", "")
    exclude, last_seen = exclude or {}, last_seen or {}
    by_corp = defaultdict(list)
    for r in dart_list.equity_registrations(start, end):
        by_corp[r["corp_code"]].append(r)
    listing = krx_listing_dates(base_date, detected)
    result_reports = dart_list.result_reports(start, end)

    registry, terms = [], []
    for corp, filings in by_corp.items():
        estk = {x["rcept_no"]: x for x in dart_estk.estk_for_corp(corp, filings)}
        ipo_id = make_ipo_id(corp, filings[0]["rcept_no"])
        corp_listing = listing.get(corp, ("", ""))
        pre_dates = [f["rcept_dt"] for f in filings if corp_listing[1] and f["rcept_dt"] <= corp_listing[1]]
        universe, note = universe_decision(max(pre_dates) if pre_dates else None, corp_listing[1], sample_start,
                                           exclude.get(corp_listing[0]))
        pre_sample = is_pre_sample(note, corp_listing[1], buffer_start)
        final = _final_price(filings, universe or pre_sample, result_reports.get(corp, []), corp_listing[1])
        seen = last_seen.get(corp_listing[0], "")
        delisted = bool(seen and last_day and seen < last_day)
        registry.append(_registry_row(ipo_id, corp, filings, estk, corp_listing, final, universe, note, (seen, delisted), pre_sample))
        terms += _terms_rows(ipo_id, filings, estk, final)
    return registry, terms


def write(rows, cols, name):
    config.MART.mkdir(parents=True, exist_ok=True)
    out = config.MART / name
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
    return out


if __name__ == "__main__":
    start = sys.argv[1] if len(sys.argv) > 1 else config.BUFFER_START
    end = sys.argv[2] if len(sys.argv) > 2 else date.today().strftime("%Y%m%d")
    base_date = sys.argv[3] if len(sys.argv) > 3 else "20261026"
    sample_start = settings.load_universe()["sample_start"].replace("-", "")
    import build_sample   # KRX 일별 raw 로 찾은 신규상장 (폐지 종목 포함)·코넥스 이전상장 등 (D11)
    from store.bars import last_seen_dates
    rows = build_sample.detected_listings(base_date, sample_start)
    last_seen, last_day = last_seen_dates(config.BUFFER_START, base_date)
    reg, terms = build(start, end, base_date, sample_start=sample_start,
                       exclude={r["code"]: r["excluded"] for r in rows if r["excluded"]},
                       detected={r["code"]: r["list_date"] for r in rows if not r["excluded"]},
                       last_seen=last_seen, last_day=last_day)
    gaps = universe_gaps(rows, reg, last_seen, last_day, mapped=set(dart_api.corp_code_map()))
    print(f"[DART] {write(gaps, ['name', 'code', 'list_date', 'reason'], 'universe_gaps.csv')} "
          f"(KRX 탐지 대비 누락 {len(gaps)}건, 상장폐지 의심 {sum(g['reason'].startswith('상장폐지') for g in gaps)}건, "
          f"대상 중 상장 뒤 사라진 종목 {sum(bool(r['delisted_after_listing']) for r in reg if r['in_trading_universe'])}건)")
    uni = [r for r in reg if r["in_trading_universe"]]
    ok = [r for r in uni if r["offer_price_status"] == Status.CONFIRMED.value]
    print(f"[DART] {write(reg, REGISTRY_COLS, 'dart_ipo_registry.csv')} ({len(reg)}곳, IPO 후보 {sum(r['is_ipo_candidate'] for r in reg)}, 매매 대상 {len(uni)}, 표본 이전(참고용) {sum(bool(r['pre_sample']) for r in reg)}, 확정 공모가 확인 {len(ok)})")
    print(f"[DART] {write(terms, TERMS_COLS, 'dart_offer_terms.csv')} ({len(terms)}건)")
