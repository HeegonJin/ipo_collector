"""수요 지표 마트: 매매 대상 종목마다 수요예측 경쟁률·확약·유통가능 물량·락업 일정·일반청약 경쟁률을 DART 원문에서 뽑아 한 줄로 만든다.

  python build_demand_mart.py 20230101 20261029      # → data/2_mart/dart_demand.csv

입력은 build_dart_registry 가 만든 data/2_mart/dart_ipo_registry.csv·dart_offer_terms.csv 와 DART 실적보고서 목록.
원문은 data/0_raw/dart/doc 캐시를 쓴다 (확정가 때 이미 받은 공시라 대개 새로 받지 않는다).
모든 값은 상장 전에 공시된 것이라 상장일 판단에 look-ahead 가 없다. 공개 시점은 *_available_dt (공시 접수일).
읽지 못한 값은 빈 칸이다 (0 으로 채우지 않는다). *_status 가 '확인' 인 것만 교차 검증을 통과한 값이다.
"""
import csv
import json
import sys
from datetime import date

import config
import dart_demand
import dart_list
from core.schema import Status

NO = Status.UNVERIFIED.value
DEMAND_COLS = (
    ["ipo_id", "corp_code", "stock_code", "corp_name", "list_dd", "pre_sample",
     "demand_rcept", "demand_available_dt", "demand_n", "demand_qty", "demand_ratio", "demand_status", "demand_note",
     "commit_rcept", "commit_available_dt", "commit_ratio", "commit_6m_qty", "commit_3m_qty", "commit_1m_qty", "commit_15d_qty",
     "commit_status", "commit_note",
     "float_rcept", "float_available_dt", "float_shares", "float_pct", "listed_shares", "float_status", "float_note",
     "locked_total", "lockups", "lockup_coverage", "lockup_status",
     "alloc_rcept", "alloc_available_dt", "retail_ratio", "retail_subscribers", "final_commit_ratio",
     "final_commit_6m_pct", "final_commit_3m_pct", "final_commit_1m_pct", "final_commit_15d_pct", "alloc_status", "alloc_note"])


def _num(v):
    return float(v) if v not in (None, "") else None


# 지표 묶음: (묶음 안의 열, 값이 있다고 볼 열). 묶음마다 값이 있는 가장 늦은 상장 전 공시에서 가져오고 그 공시 번호·접수일을 남긴다.
_GROUPS = {
    "demand": (("demand_n", "demand_qty", "demand_ratio", "demand_status", "demand_note"), "demand_ratio"),
    "commit": (("commit_qty", "commit_ratio", "commit_status", "commit_note"), "commit_ratio"),
    "float": (("float_shares", "float_pct", "listed_shares", "float_status", "float_note", "lockups", "locked_total", "lockup_status"),
              "float_shares"),
}


def _demand_part(reg: dict, terms: list[dict]) -> dict:
    """상장 전 공시를 가장 늦은 것부터 열어, 묶음(수요예측·확약·유통가능/락업)마다 값이 있는 첫 공시에서 가져온다.
    정정본이 앞선 공시를 덮지만, 확약·유통가능 표는 최종 정정에 빠지고 최초 신고서에만 있는 경우가 있다."""
    pre = sorted((t for t in terms if t["rcept_dt"] <= reg["list_dd"]), key=lambda t: t["rcept_no"], reverse=True)
    out = {**dart_demand._empty_demand(), **{f"{g}_{k}": "" for g in _GROUPS for k in ("rcept", "available_dt")}}
    if not pre:
        return {**out, "demand_note": "공시 없음 (상장 전 지분증권 신고서 없음)"}
    errors, pending, first = [], set(_GROUPS), None
    for t in pre:
        if not pending:
            break
        try:
            d = dart_demand.demand_for(t["rcept_no"], _num(t.get("stock_cnt")))
        except (RuntimeError, OSError, ValueError) as e:       # 한 건 조회 실패가 전체 수집을 멈추지 않게 한다
            errors.append(f"{t['rcept_no']}: {e}")
            continue
        first = first or d
        for g in sorted(pending):
            cols, marker = _GROUPS[g]
            if d[marker] is not None:
                out.update({c: d[c] for c in cols})
                out.update({f"{g}_rcept": t["rcept_no"], f"{g}_available_dt": t["rcept_dt"]})
                pending.discard(g)
    if first is None:
        return {**out, "demand_note": "원문 조회 실패: " + "; ".join(errors)[:200]}
    for g in pending:                                          # 어느 공시에도 없으면 첫 공시의 '미확인' 사유를 남긴다
        out.update({c: first[c] for c in _GROUPS[g][0]})
    return out


def _alloc_part(reg: dict, reports: list[dict], after_dt: str) -> dict:
    out = {"retail_ratio": None, "retail_subscribers": None, "final_commit_ratio": None, "final_commit_pct": None,
           "alloc_status": NO, "alloc_note": "증권발행실적보고서 없음", "alloc_rcept": "", "alloc_available_dt": ""}
    report = dart_list.pick_result_report([r for r in reports if r["rcept_dt"] <= reg["list_dd"]], after_dt or "")
    if not report:
        return out
    try:
        a = dart_demand.allocation_for(report["rcept_no"])
    except (RuntimeError, OSError, ValueError) as e:
        return {**out, "alloc_note": f"원문 조회 실패: {e}"[:200]}
    return {**a, "alloc_rcept": report["rcept_no"], "alloc_available_dt": report["rcept_dt"]}


def collect_ipo(reg: dict, terms: list[dict], reports: list[dict]) -> dict:
    d = _demand_part(reg, terms)
    a = _alloc_part(reg, reports, d["demand_available_dt"])
    cq = d["commit_qty"] or {}
    pct = a["final_commit_pct"] or {}
    lockups = d["lockups"] or {}
    coverage = sum(lockups.values()) / d["locked_total"] if lockups and d["locked_total"] else None
    row = {k: reg.get(k, "") for k in ("ipo_id", "corp_code", "stock_code", "corp_name", "list_dd", "pre_sample")}
    row.update({k: d[k] for k in ("demand_rcept", "demand_available_dt", "demand_n", "demand_qty", "demand_ratio", "demand_status",
                                  "demand_note", "commit_rcept", "commit_available_dt", "commit_ratio", "commit_status", "commit_note",
                                  "float_rcept", "float_available_dt", "float_shares", "float_pct", "listed_shares", "float_status",
                                  "float_note", "locked_total", "lockup_status")})
    row.update({f"commit_{k}_qty": cq.get(k) for k in ("6m", "3m", "1m", "15d")})
    row.update(lockups=json.dumps(lockups) if lockups else None, lockup_coverage=coverage)
    row.update({k: a[k] for k in ("alloc_rcept", "alloc_available_dt", "retail_ratio", "retail_subscribers", "final_commit_ratio",
                                  "alloc_status", "alloc_note")})
    row.update({f"final_commit_{k}_pct": pct.get(k) for k in ("6m", "3m", "1m", "15d")})
    return row


def write(rows: list[dict]):
    config.MART.mkdir(parents=True, exist_ok=True)
    out = config.MART / "dart_demand.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DEMAND_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in DEMAND_COLS})
    return out


def _read(name: str) -> list[dict]:
    with open(config.MART / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build(start: str, end: str) -> list[dict]:
    registry = [r for r in _read("dart_ipo_registry.csv") if (r["in_trading_universe"] == "True" or r.get("pre_sample") == "True") and r["list_dd"]]
    terms: dict = {}
    for t in _read("dart_offer_terms.csv"):
        terms.setdefault(t["ipo_id"], []).append(t)
    reports = dart_list.result_reports(start, end)
    return [collect_ipo(r, terms.get(r["ipo_id"], []), reports.get(r["corp_code"], [])) for r in registry]


def _coverage(rows: list[dict]) -> str:
    parts = []
    for name, col in (("수요예측", "demand_status"), ("확약", "commit_status"), ("유통가능", "float_status"),
                      ("락업", "lockup_status"), ("청약·최종확약", "alloc_status")):
        ok = sum(r[col] == Status.CONFIRMED.value for r in rows)
        parts.append(f"{name} {ok}/{len(rows)}")
    return ", ".join(parts)


if __name__ == "__main__":
    start = sys.argv[1] if len(sys.argv) > 1 else config.BUFFER_START
    end = sys.argv[2] if len(sys.argv) > 2 else date.today().strftime("%Y%m%d")
    rows = build(start, end)
    print(f"[DART] {write(rows)} ({len(rows)}종목) 교차 검증 통과(확인): {_coverage(rows)}")
