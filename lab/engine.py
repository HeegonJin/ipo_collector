"""전략 실험 앱의 평가 엔진: 사람이 고른 조건·진입·보유기간을 종목별 특징 표에 적용해 수익률을 낸다.

숫자 계산은 모두 코드가 한다 (LLM 은 판단하지 않는다). 비용 공식은 A0 와 같은 evaluate.outcomes 의 것을 쓴다.

용어
  phase  pre : 상장 전에 확정되는 값이라 look-ahead 가 없다
         d0  : 상장일 장 마감 뒤에야 정해지는 값. D0 종가 진입과 함께 쓰면 15:20 판단에는 못 쓰는 정보 → '상한 추정'
  in_design : 팀 설계도(아키텍처 문서 전략 A)에 있는 조건인지. False 는 '설계도 외 탐색'으로 화면에 표시한다
  진입    d0_close : 상장일 종가 매수 (설계도) / d1_open : 다음 거래일 시가 매수 (look-ahead 를 피하는 비교용)
  보유    진입한 날로부터 N 거래일 뒤 시가에 판다 (d0_close·N=1 이 A0)
"""
import statistics as st

import report
from evaluate.outcomes import _net

CONDITIONS = [
    {"id": "band_pos", "label": "확정 공모가의 희망밴드 내 위치", "hint": "0=하단, 1=상단, 1 초과=밴드 상단 초과",
     "phase": "pre", "unit": "", "min": -1.0, "max": 3.0, "step": 0.25, "in_design": False},
    {"id": "offer_amount_bil", "label": "공모금액", "hint": "공모 주식 수 × 확정 공모가",
     "phase": "pre", "unit": "억원", "min": 0.0, "max": 3000.0, "step": 50.0, "in_design": False},
    {"id": "d0_ret_vs_offer", "label": "상장일 종가의 공모가 대비 수익률", "hint": "음수면 공모가 아래로 마감",
     "phase": "d0", "unit": "%", "min": -50.0, "max": 400.0, "step": 10.0, "in_design": True},
    {"id": "d0_drop_from_high", "label": "상장일 종가의 당일 고점 대비", "hint": "음수일수록 고점에서 많이 밀림",
     "phase": "d0", "unit": "%", "min": -60.0, "max": 0.0, "step": 2.5, "in_design": True},
    {"id": "d0_index_chg", "label": "상장일 코스닥 등락률", "hint": "상장일 코스닥 종가의 전일 대비",
     "phase": "d0", "unit": "%", "min": -8.0, "max": 8.0, "step": 0.25, "in_design": True},
]
BY_ID = {c["id"]: c for c in CONDITIONS}
ENTRIES = {
    "d0_close": {"label": "상장일 종가 매수", "in_design": True},
    "d1_open": {"label": "다음 거래일 시가 매수", "in_design": False},
}
HOLDS = (1, 3, 5)


def normalize(params: dict) -> dict:
    """앱이 보낸 파라미터를 검증하고 켜진 조건만 남긴 정규형으로 바꾼다. 이 정규형이 시도 횟수의 기준(해시)이다."""
    entry, hold = params.get("entry"), params.get("hold")
    if entry not in ENTRIES:
        raise ValueError(f"알 수 없는 진입 시점: {entry!r}")
    if hold not in HOLDS:
        raise ValueError(f"보유 기간은 {HOLDS} 중 하나여야 함: {hold!r}")
    conds = {}
    for cid, c in (params.get("conditions") or {}).items():
        if cid not in BY_ID:
            raise ValueError(f"알 수 없는 조건: {cid!r}")
        if not c.get("enabled"):
            continue
        lo, hi, meta = float(c["lo"]), float(c["hi"]), BY_ID[cid]
        if lo > hi:
            raise ValueError(f"{cid}: 하한이 상한보다 큼 ({lo} > {hi})")
        if lo < meta["min"] or hi > meta["max"]:
            raise ValueError(f"{cid}: 범위 밖 ({meta['min']}~{meta['max']})")
        conds[cid] = [lo, hi]
    return {"entry": entry, "hold": int(hold), "conditions": dict(sorted(conds.items()))}


def select(rows: list[dict], eff: dict) -> tuple[list[dict], dict]:
    """정규형 조건을 모두 만족하는 행과, 조건별로 '값을 몰라서' 제외한 건수. 값이 없으면 통과시키지도 0 으로 채우지도 않는다."""
    kept, unknown = [], {}
    for r in rows:
        ok = True
        for cid, (lo, hi) in eff["conditions"].items():
            v = r.get(cid)
            if v is None:
                unknown[cid] = unknown.get(cid, 0) + 1
                ok = False
                break
            if not lo <= v <= hi:
                ok = False
                break
        if ok:
            kept.append(r)
    return kept, unknown


def _prices(r: dict, eff: dict):
    k = eff["hold"]
    if eff["entry"] == "d0_close":
        return r["close_d0"], r["open_d"].get(k)
    return r["open_d"].get(1), r["open_d"].get(1 + k)


def _trades(rows: list[dict], eff: dict, costs: dict):
    trades, no_exit = [], 0
    for r in rows:
        entry_px, exit_px = _prices(r, eff)
        if not entry_px or not exit_px:
            no_exit += 1
            continue
        year = int(r["list_date"][:4])
        tax = costs["kosdaq_sell_tax"]
        if year not in tax:
            raise ValueError(f"매도세율이 없는 연도: {year}")
        net = _net(exit_px, entry_px, (costs["commission_per_side"], costs["slippage_per_side"], tax[year]))
        trades.append({"ipo_id": r["ipo_id"], "name": r["name"], "list_date": r["list_date"],
                       "entry_px": entry_px, "exit_px": exit_px, "net_ret": net})
    return trades, no_exit


def evaluate(rows: list[dict], params: dict, costs: dict, split: str) -> dict:
    """한 구간(split)에 파라미터를 적용한 결과. 기준선은 같은 진입·보유에서 조건만 뺀 것이다."""
    eff = normalize(params)
    pool = [r for r in rows if r["split"] == split]
    fillable = [r for r in pool if not r["limit_up"]]          # 상한가 종가는 체결이 불확실 → 주 결과에서 제외
    kept, unknown = select(fillable, eff)
    trades, no_exit = _trades(kept, eff, costs)
    base_trades, _ = _trades(fillable, {**eff, "conditions": {}}, costs)
    d0_used = any(BY_ID[c]["phase"] == "d0" for c in eff["conditions"])
    return {
        "params": eff, "split": split, "trades": trades,
        "stats": summarize([t["net_ret"] for t in trades]), "baseline": summarize([t["net_ret"] for t in base_trades]),
        "excluded": {"limit_up": len(pool) - len(fillable), "no_exit_price": no_exit,
                     **({"unknown_value": sum(unknown.values())} if unknown else {}), **{k: v for k, v in unknown.items()}},
        "lookahead": eff["entry"] == "d0_close" and d0_used,
        "pool": len(pool),
    }


def summarize(vals: list[float]) -> dict:
    s = report.summarize(vals)
    if not s:
        return {"n": 0}
    s["se"] = st.stdev(vals) / len(vals) ** 0.5 if len(vals) > 1 else None   # 평균의 표준오차 (우연 기대치 계산에 쓴다)
    return s
