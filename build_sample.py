"""
0_raw(KRX 날짜별 응답) → 신규상장 표본 + 첫 실험 계산.

신규상장 탐지 규칙
  1) 코스닥 일별매매정보에 '처음 나타난 날'을 상장일(D0)로 본다.
  2) BUFFER_START~SAMPLE_START 사이에 이미 거래되던 종목은 신규상장이 아니다.
  3) 제외 (D11 + 기획 v3.1):
     - 이름에 스팩·리츠 → 제외
     - 같은 종목코드나 같은 이름이 코넥스 일별매매정보에 먼저 있었으면 → 코넥스 이전상장, 제외
     - 재상장·분할재상장 등 '공모 없는 상장'은 DART 단계(dart_api.py)에서 증권신고서 유무로 거른다
  4) 공모가 추정: 상장일 기준가 = 공모가. KRX 응답의 '전일대비'가 기준가 대비이므로
     공모가 = 종가 − 전일대비. DART 공모가와 다르면 빠진 값 목록에 올린다.

첫 실험 (D5): D0 종가 매수 → D1 시가 매도.
  - D0 종가가 공모가의 4배(상한가)면 '종가 매수 체결 불확실' 표시
  - 비용: 수수료 양쪽, 슬리피지 양쪽, 매도 시 거래세(연도별)
"""
import csv
import json
from collections import OrderedDict

import config
from krx_api import daterange


def num(v):
    """'61,500', '-', '' 같은 문자열을 숫자로. 못 읽으면 None."""
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def short_code(r):
    """6자리 단축코드. 일별매매정보의 ISU_CD가 단축코드인지 ISIN(KR7......)인지 첫 실행 때 확인(VERIFY).
    2024년 이후 신규 종목은 0158S0 처럼 영문이 섞일 수 있으므로 문자열로만 다룬다."""
    if r.get("ISU_SRT_CD"):
        return r["ISU_SRT_CD"]
    c = r.get("ISU_CD") or ""
    return c[3:9] if len(c) == 12 and c.startswith("KR") else c


def load_days(service: str, start: str, end: str) -> "OrderedDict[str, list[dict]]":
    days = OrderedDict()
    for d in daterange(start, end):
        p = config.RAW / "krx" / service / f"{d}.json"
        if p.exists():
            rows = json.loads(p.read_text(encoding="utf-8"))
            if rows:
                days[d] = rows
    return days


def kosdaq_index(idx_days):
    out = {}
    for d, rows in idx_days.items():
        for r in rows:
            if r.get("IDX_NM") == "코스닥":
                out[d] = {"open": num(r.get("OPNPRC_IDX")), "close": num(r.get("CLSPRC_IDX")),
                          "chg_pct": num(r.get("FLUC_RT"))}
    return out


def detect_listings(ksq_days, knx_days, sample_start):
    """반환: 신규상장 후보 목록 (제외된 것도 사유와 함께 포함)."""
    seen = set()
    konex_codes, konex_names = set(), set()
    trading_days = list(ksq_days.keys())
    knx_iter = iter(knx_days.items())
    knx_buffer = list(knx_iter)
    knx_idx = 0
    result = []

    for i, d in enumerate(trading_days):
        # 이 날까지의 코넥스 종목을 누적 (같은 날 코넥스 → 코스닥 이동도 잡기 위해 '이 날 이전'까지만)
        while knx_idx < len(knx_buffer) and knx_buffer[knx_idx][0] < d:
            for r in knx_buffer[knx_idx][1]:
                konex_codes.add(r.get("ISU_CD"))
                konex_names.add((r.get("ISU_NM") or "").strip())
            knx_idx += 1

        for r in ksq_days[d]:
            code = r.get("ISU_CD")
            if code in seen:
                continue
            seen.add(code)
            if d < sample_start:
                continue  # 탐지 여유 구간에 이미 있던 종목

            name = (r.get("ISU_NM") or "").strip()
            close, cmp_prev = num(r.get("TDD_CLSPRC")), num(r.get("CMPPREVDD_PRC"))
            offer_est = close - cmp_prev if close is not None and cmp_prev is not None else None

            reason = ""
            # 이름 키워드 또는 소속부가 SPAC 이면 스팩이다 ('…호기업인수목적' 처럼 키워드가 없는 이름도 소속부로 거른다)
            if any(k in name for k in config.EXCLUDE_NAME_KEYWORDS) or (r.get("SECT_TP_NM") or "").startswith("SPAC"):
                reason = "스팩·리츠"
            elif code in konex_codes or name in konex_names:
                reason = "코넥스 이전상장"

            nxt = None
            if i + 1 < len(trading_days):
                d1 = trading_days[i + 1]
                nxt = next((x for x in ksq_days[d1] if x.get("ISU_CD") == code), None)

            result.append({
                "code": code,
                "short_code": short_code(r),
                "name": name,
                "list_date": d,
                "sect": r.get("SECT_TP_NM", ""),
                "offer_price_est": offer_est,
                "d0_open": num(r.get("TDD_OPNPRC")),
                "d0_high": num(r.get("TDD_HGPRC")),
                "d0_low": num(r.get("TDD_LWPRC")),
                "d0_close": close,
                "d0_volume": num(r.get("ACC_TRDVOL")),
                "d0_value": num(r.get("ACC_TRDVAL")),
                "d0_mktcap": num(r.get("MKTCAP")),
                "list_shares": num(r.get("LIST_SHRS")),
                "d1_date": trading_days[i + 1] if i + 1 < len(trading_days) else "",
                "d1_open": num(nxt.get("TDD_OPNPRC")) if nxt else None,
                "excluded": reason,
            })
    return result


def apply_listing_crosscheck(rows, list_dd_by_code: dict):
    """일별 데이터에 처음 나타난 날(D0)을 KRX 종목기본정보의 상장일(LIST_DD)과 대조한다.

    거래정지 등으로 일별 데이터에서 빠졌다가 다시 나타난 기존 종목은 D0 가 LIST_DD 보다 훨씬 늦어 신규상장으로 오인된다.
    종목기본정보는 현재 상장 종목의 스냅샷이라 상장폐지 종목은 없다 → 스냅샷에 없으면 '미실시'로 두고 제외하지 않는다.
    이미 다른 사유로 제외된 행은 그 사유를 유지한다."""
    for r in rows:
        list_dd = list_dd_by_code.get(r["code"])
        if not list_dd:
            r["list_dd"], r["list_dd_check"] = "", "미실시"
            continue
        r["list_dd"] = list_dd
        if list_dd == r["list_date"]:
            r["list_dd_check"] = "일치"
        else:
            r["list_dd_check"] = "불일치"
            if not r["excluded"]:
                r["excluded"] = "재등장 의심(상장일 불일치)"
    return rows


def apply_experiment(rows, idx):
    for r in rows:
        offer, c0, o1 = r["offer_price_est"], r["d0_close"], r["d1_open"]
        year = int(r["list_date"][:4])
        tax = config.KOSDAQ_SELL_TAX.get(year)

        r["d0_close_vs_offer"] = (c0 / offer - 1) if offer and c0 else None
        r["buy_at_limit_up"] = bool(offer and c0 and c0 >= offer * 4 * 0.999)
        r["gross_ret"] = (o1 / c0 - 1) if c0 and o1 else None
        if r["gross_ret"] is not None and tax is not None:
            buy = c0 * (1 + config.COMMISSION_PER_SIDE + config.SLIPPAGE_PER_SIDE)
            sell = o1 * (1 - config.COMMISSION_PER_SIDE - config.SLIPPAGE_PER_SIDE - tax)
            r["net_ret"] = sell / buy - 1
        else:
            r["net_ret"] = None

        i0, i1 = idx.get(r["list_date"]), idx.get(r["d1_date"])
        r["kosdaq_d0_chg_pct"] = i0["chg_pct"] if i0 else None
        r["kosdaq_overnight"] = (i1["open"] / i0["close"] - 1) if i0 and i1 and i0["close"] and i1["open"] else None
    return rows


# 기획 v3.1 S2~S8 중 KRX 일별 데이터로 못 채우는 칸 → G1 '빠진 값' 목록에 그대로 공개
PENDING_COLUMNS = {
    "offer_price_dart": "DART 증권발행실적보고서 (S1 교차검증)",
    "listing_type": "DART 증권신고서 유무로 공모 상장 확인 (재상장·분할재상장 제외)",
    "tech_special": "기술특례 여부 (KIND·투자설명서)",
    "float_ratio": "DART 투자설명서 '상장 후 유통가능 주식' (S2)",
    "inst_demand_ratio": "DART 발행조건확정 증권신고서 수요예측 (S3)",
    "lockup_alloc_ratio": "DART 증권발행실적보고서 확약 배정 (S4)",
    "retail_sub_ratio": "DART 증권발행실적보고서 청약 (S4)",
    "lockup_release": "SEIBRO 의무보호예수 해제 (S5)",
    "inst_net_buy_d0": "KRX 투자자별 거래실적 (S6) — Open API 미제공, 키움 대체 검토",
    "minute_bars_d0": "키움 ka10080 분봉 (S7) — 과거 제공 범위 확인 필요",
    "macro_regime": "SM 매크로 에이전트 JSON (국면별 기록용)",
}

COLUMNS = ["code", "short_code", "name", "list_date", "list_dd", "list_dd_check", "sect", "excluded",
           "offer_price_est", "d0_open", "d0_high", "d0_low", "d0_close", "d0_close_vs_offer",
           "d0_volume", "d0_value", "d0_mktcap", "list_shares", "buy_at_limit_up",
           "d1_date", "d1_open", "gross_ret", "net_ret", "kosdaq_d0_chg_pct", "kosdaq_overnight",
           *PENDING_COLUMNS.keys()]


def write_outputs(rows, tag):
    config.MART.mkdir(parents=True, exist_ok=True)
    config.META.mkdir(parents=True, exist_ok=True)
    out = config.MART / f"ipo_sample_{tag}.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in COLUMNS})

    eligible = [r for r in rows if not r["excluded"]]
    lines = [f"# 빠진 값 목록 ({tag})", "",
             f"- 탐지된 신규 종목 {len(rows)}건 / 제외 {len(rows) - len(eligible)}건 / 대상 {len(eligible)}건", ""]
    lines += ["## 아직 수집하지 않은 열 (전 종목 공통)", "", "| 열 | 출처 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in PENDING_COLUMNS.items()]
    lines += ["", "## 종목별로 비어 있는 값", "", "| 종목 | 상장일 | 빠진 값 |", "|---|---|---|"]
    core = ["offer_price_est", "d0_close", "d1_open", "kosdaq_overnight"]
    for r in eligible:
        miss = [k for k in core if r.get(k) is None]
        if r["buy_at_limit_up"]:
            miss.append("상한가 종가(체결 불확실)")
        if miss:
            lines.append(f"| {r['name']} ({r['code']}) | {r['list_date']} | {', '.join(miss)} |")
    (config.META / f"missing_{tag}.md").write_text("\n".join(lines), encoding="utf-8")
    return out


def detected_listings(end: str, sample_start: str) -> list[dict]:
    """KRX 일별 데이터로 찾은 신규 종목 전체 (제외 사유 포함). 일별 데이터는 폐지 종목도 폐지일까지 담고 있다."""
    ksq = load_days("ksq_daily", config.BUFFER_START, end)
    knx = load_days("knx_daily", config.BUFFER_START, end)
    return detect_listings(ksq, knx, sample_start.replace("-", ""))


def excluded_listings(end: str, sample_start: str) -> dict:
    """KRX 일별 데이터로 찾은 신규 종목 중 제외 사유가 있는 것 {종목코드: 사유} (스팩·리츠, 코넥스 이전상장).
    DART 쪽 매매 대상에서 코넥스 이전상장을 빼는 데 쓴다 (D11)."""
    return {r["code"]: r["excluded"] for r in detected_listings(end, sample_start) if r["excluded"]}


def load_list_dd(base_date: str) -> dict:
    """KRX 종목기본정보 스냅샷 → {종목코드: 상장일}. 못 받으면 조용히 건너뛰지 않고 실패한다."""
    import krx_api
    rows = krx_api.fetch("ksq_base", base_date)
    if not rows:
        raise RuntimeError(f"KRX ksq_base({base_date}) 응답이 비어 있음 — 상장일 교차검증을 할 수 없다")
    return {r["ISU_SRT_CD"]: r["LIST_DD"] for r in rows}


def build(end: str, sample_start: str | None = None, tag: str = "all", list_dd: dict | None = None):
    """list_dd 를 주면 일별 데이터로 찾은 상장일을 그 값(KRX 종목기본정보)과 대조한다. 안 주면 대조하지 않고 '미실시'로 남긴다."""
    sample_start = sample_start or config.SAMPLE_START
    ksq = load_days("ksq_daily", config.BUFFER_START, end)
    knx = load_days("knx_daily", config.BUFFER_START, end)
    idx = kosdaq_index(load_days("kosdaq_idx", config.BUFFER_START, end))
    rows = detect_listings(ksq, knx, sample_start)
    rows = apply_listing_crosscheck(rows, list_dd or {})
    rows = apply_experiment(rows, idx)
    out = write_outputs(rows, tag)
    print(f"[표본] {out} ({len(rows)}건, 제외 {sum(1 for r in rows if r['excluded'])}건)")
    return rows


if __name__ == "__main__":
    import sys
    from datetime import date, timedelta
    end = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    start = sys.argv[2] if len(sys.argv) > 2 else config.SAMPLE_START
    build(end, start, tag=f"{start}_{end}", list_dd=load_list_dd(end))
