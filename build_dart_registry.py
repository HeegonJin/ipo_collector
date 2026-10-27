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
from core.ids import make_ipo_id
from core.schema import Status

REGISTRY_COLS = ["ipo_id", "corp_code", "stock_code", "corp_name", "first_rcept_no", "first_rcept_dt", "sale_method",
                 "is_ipo_candidate", "list_dd", "in_trading_universe", "n_filings", "last_kind",
                 "offer_price_final", "offer_price_status", "offer_price_rcept", "band_low", "band_high",
                 "offer_price_note"]
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
    try:
        base = {x["ISU_SRT_CD"]: x["LIST_DD"] for x in krx_api.fetch("ksq_base", base_date)}
    except Exception as e:  # 키·승인 문제로 못 받으면 상장일 없이 진행하고 건강판에서 드러나게 한다
        print(f"[경고] KRX 종목기본정보를 받지 못함({type(e).__name__}) — list_dd 비움")
        return {}
    by_corp = {}
    for stock, corp in dart_api.corp_code_map().items():
        if stock in base:
            by_corp[corp] = (stock, base[stock])
    return by_corp


def build(start: str, end: str, base_date: str):
    regs = dart_list.equity_registrations(start, end)
    by_corp = defaultdict(list)
    for r in regs:
        by_corp[r["corp_code"]].append(r)
    listing = krx_listing_dates(base_date)

    registry, terms = [], []
    for corp, filings in by_corp.items():
        estk = {x["rcept_no"]: x for x in dart_estk.estk_for_corp(corp, filings)}
        first = filings[0]
        ipo_id = make_ipo_id(corp, first["rcept_no"])
        sale_method = next((x.get("sale_method") for x in estk.values() if x.get("sale_method")), "")
        stock, list_dd = listing.get(corp, ("", ""))
        universe = listed_within_window(first["rcept_dt"], list_dd)

        final = {"offer_price": None, "status": Status.UNVERIFIED.value, "rcept_no": "", "band_low": None,
                 "band_high": None, "note": "발행조건확정 공시 없음"}
        confirmed = [f["rcept_no"] for f in filings if f["kind"] == "발행조건확정"]
        if universe and confirmed:  # 원문 내려받기는 매매 대상 후보에만 한다
            final = dart_terms.final_offer_terms(confirmed)
        elif confirmed:
            final["note"] = "매매 대상 아님: 원문 미조회"

        registry.append({
            "ipo_id": ipo_id, "corp_code": corp, "stock_code": stock, "corp_name": first["corp_name"],
            "first_rcept_no": first["rcept_no"], "first_rcept_dt": first["rcept_dt"], "sale_method": sale_method,
            "is_ipo_candidate": sale_method == "일반공모", "list_dd": list_dd, "in_trading_universe": universe,
            "n_filings": len(filings), "last_kind": filings[-1]["kind"],
            "offer_price_final": final["offer_price"], "offer_price_status": final["status"],
            "offer_price_rcept": final.get("rcept_no", ""), "band_low": final.get("band_low"),
            "band_high": final.get("band_high"), "offer_price_note": final.get("note", ""),
        })
        for f in filings:
            t = estk.get(f["rcept_no"], {})
            is_final = f["rcept_no"] == final.get("rcept_no")
            terms.append({
                "ipo_id": ipo_id, "rcept_no": f["rcept_no"], "rcept_dt": f["rcept_dt"], "kind": f["kind"],
                "available_at": available_at(f["rcept_dt"]),
                "offer_price": final["offer_price"] if is_final else None,
                "offer_price_status": final["status"] if is_final else Status.UNVERIFIED.value,
                "offer_price_expected": t.get("offer_price"),
                **{k: t.get(k) for k in ("stock_cnt", "old_share_cnt", "offer_amount", "sub_start", "sub_end",
                                         "pay_date", "sale_method")},
            })
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
    reg, terms = build(start, end, base_date)
    uni = [r for r in reg if r["in_trading_universe"]]
    ok = [r for r in uni if r["offer_price_status"] == Status.CONFIRMED.value]
    print(f"[DART] {write(reg, REGISTRY_COLS, 'dart_ipo_registry.csv')} ({len(reg)}곳, IPO 후보 {sum(r['is_ipo_candidate'] for r in reg)}, 매매 대상 {len(uni)}, 확정 공모가 확인 {len(ok)})")
    print(f"[DART] {write(terms, TERMS_COLS, 'dart_offer_terms.csv')} ({len(terms)}건)")
