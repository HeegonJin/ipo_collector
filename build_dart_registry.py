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
                 "is_ipo_candidate", "list_dd", "in_trading_universe", "universe_note", "n_filings", "last_kind",
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


def krx_listing_dates(base_date: str) -> dict:
    """corp_code → (stock_code, LIST_DD). KRX 종목기본정보가 없으면 빈 dict."""
    # 못 받거나 비어 있으면 매매 대상이 조용히 0건이 되므로 경고로 넘기지 않고 실패시킨다.
    try:
        rows = krx_api.fetch("ksq_base", base_date)
    except Exception as e:
        raise RuntimeError(f"KRX ksq_base({base_date}) 종목기본정보를 받지 못함: {type(e).__name__}: {e}") from e
    if not rows:
        raise RuntimeError(f"KRX ksq_base({base_date}) 응답이 비어 있음 — 기준일이 휴장일이거나 서비스 미승인일 수 있다")
    base = {x["ISU_SRT_CD"]: x["LIST_DD"] for x in rows}
    by_corp = {}
    for stock, corp in dart_api.corp_code_map().items():
        if stock in base:
            by_corp[corp] = (stock, base[stock])
    return by_corp


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
        return False, "표본 시작일 이전 상장"
    return True, ""


def _registry_row(ipo_id, corp, filings, estk, listing, final, universe, note="") -> dict:
    first = filings[0]
    sale_method = next((x.get("sale_method") for x in estk.values() if x.get("sale_method")), "")
    stock, list_dd = listing
    return {
        "ipo_id": ipo_id, "corp_code": corp, "stock_code": stock, "corp_name": first["corp_name"],
        "first_rcept_no": first["rcept_no"], "first_rcept_dt": first["rcept_dt"], "sale_method": sale_method,
        "is_ipo_candidate": sale_method == "일반공모", "list_dd": list_dd, "in_trading_universe": universe,
        "universe_note": note, "n_filings": len(filings), "last_kind": filings[-1]["kind"],
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


def build(start: str, end: str, base_date: str, exclude: dict | None = None, sample_start: str | None = None):
    """exclude: {종목코드: 사유} — KRX 일별 데이터로 찾은 코넥스 이전상장 등 (build_sample.excluded_listings).
    sample_start: 이 날짜 이전 상장은 매매 대상이 아니다 (기본은 config/universe_v1.yaml)."""
    sample_start = sample_start or settings.load_universe()["sample_start"].replace("-", "")
    exclude = exclude or {}
    by_corp = defaultdict(list)
    for r in dart_list.equity_registrations(start, end):
        by_corp[r["corp_code"]].append(r)
    listing = krx_listing_dates(base_date)
    result_reports = dart_list.result_reports(start, end)

    registry, terms = [], []
    for corp, filings in by_corp.items():
        estk = {x["rcept_no"]: x for x in dart_estk.estk_for_corp(corp, filings)}
        ipo_id = make_ipo_id(corp, filings[0]["rcept_no"])
        corp_listing = listing.get(corp, ("", ""))
        pre_dates = [f["rcept_dt"] for f in filings if corp_listing[1] and f["rcept_dt"] <= corp_listing[1]]
        universe, note = universe_decision(max(pre_dates) if pre_dates else None, corp_listing[1], sample_start,
                                           exclude.get(corp_listing[0]))
        final = _final_price(filings, universe, result_reports.get(corp, []), corp_listing[1])
        registry.append(_registry_row(ipo_id, corp, filings, estk, corp_listing, final, universe, note))
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
    import build_sample   # KRX 일별 raw 로 찾은 코넥스 이전상장 등 (D11)
    reg, terms = build(start, end, base_date, exclude=build_sample.excluded_listings(base_date, sample_start),
                       sample_start=sample_start)
    uni = [r for r in reg if r["in_trading_universe"]]
    ok = [r for r in uni if r["offer_price_status"] == Status.CONFIRMED.value]
    print(f"[DART] {write(reg, REGISTRY_COLS, 'dart_ipo_registry.csv')} ({len(reg)}곳, IPO 후보 {sum(r['is_ipo_candidate'] for r in reg)}, 매매 대상 {len(uni)}, 확정 공모가 확인 {len(ok)})")
    print(f"[DART] {write(terms, TERMS_COLS, 'dart_offer_terms.csv')} ({len(terms)}건)")
