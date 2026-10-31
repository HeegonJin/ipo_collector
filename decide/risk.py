"""L6 리스크 게이트: 판단(매수)에 비중을 붙이고 체결하기 어려운 건을 막는다. 숫자는 config/risk_v1.yaml (params 로 받는다).

  - 1건 목표 비중, 같은 날 합산 상한 (하룻밤 갭은 손절로 못 막으니 비중으로 통제)
  - 상한가 마감 다음 날 시가 진입 금지: 전 거래일 종가가 그 전일 대비 limit_up_pct 이상 오른 종목
  - 거래대금 한도: 진입 금액 ≤ 전 거래일 거래대금의 max_participation. 넘으면 비중을 줄이고, min_weight 아래면 진입하지 않는다
확인할 자료가 없으면(상장일 15:20 에는 당일 시세가 없다) 막지 않고 그 사실을 이유에 남긴다 — 모르는 것을 0 으로 보지 않는다.
VI 발동 여부와 장중 스냅샷은 아직 자료가 없어 보지 않는다.
"""
from dataclasses import replace

from core.pit import PitReader
from decide.runner import Decision


def _check(d: Decision, reader: PitReader, params: dict) -> tuple[float, list[str], str | None]:
    """(비중, 메모, 막는 이유). 막는 이유가 있으면 진입하지 않는다."""
    weight, notes = float(params["weight_per_trade"]), []
    if not d.short_code:
        return weight, ["종목코드 없음: 체결 가능성 확인 불가"], None
    bars = reader.bars(d.short_code, 2)
    if d.entry_rule != "next_open" or not bars:
        return weight, [f"체결 가능성(상한가·거래대금) 확인 불가: {'당일 시세가 아직 없음' if d.entry_rule != 'next_open' else '시세 없음'}"], None
    last = bars[-1]
    if len(bars) == 2 and bars[0].get("close") and last.get("close"):
        chg = (last["close"] / bars[0]["close"] - 1) * 100
        if chg >= params["limit_up_pct"]:
            return 0.0, notes, f"전 거래일 상한가 마감({chg:+.1f}%): 시가 체결 불확실"
    value = (last.get("close") or 0) * (last.get("volume") or 0)
    if value <= 0:
        return weight, ["전 거래일 거래대금을 알 수 없어 거래대금 한도를 확인하지 못함"], None
    allowed = value * params["max_participation"] / params["paper_capital_krw"]
    if allowed < weight:
        if allowed < params["min_weight"]:
            return 0.0, notes, f"거래대금 한도 초과: 전 거래일 거래대금 {value / 1e8:.1f}억원의 {params['max_participation']:.0%} 로는 최소 비중도 못 채움"
        notes.append(f"거래대금 한도로 비중 {weight:.1%} → {allowed:.1%}")
        weight = allowed
    return weight, notes, None


def apply(decisions: list[Decision], reader: PitReader, params: dict, used_today: float = 0.0) -> list[Decision]:
    """매수 판단마다 게이트를 적용해 (비중이 붙은 매수 | 막힌 관망) 으로 바꾼다. 매수가 아닌 판단은 그대로.
    used_today: 같은 날 이미 기록된 비중 합계 (장부에서 읽어 넘긴다). 판단 순서대로 한도를 채운다."""
    out, used = [], used_today
    for d in decisions:
        if d.action != "매수":
            out.append(d)
            continue
        weight, notes, veto = _check(d, reader, params)
        if veto is None:
            room = params["max_weight_per_day"] - used
            if room < params["min_weight"]:
                veto = f"같은 날 합산 한도 {params['max_weight_per_day']:.0%} 초과 (이미 {used:.1%})"
            elif weight > room:
                notes.append(f"같은 날 합산 한도로 비중 {weight:.1%} → {room:.1%}")
                weight = room
        if veto:
            out.append(replace(d, action="관망", reasons=d.reasons + (f"리스크 게이트: {veto}",), weight=None))
            continue
        used += weight
        out.append(replace(d, weight=weight, reasons=d.reasons + tuple(f"리스크 게이트: {n}" for n in notes)))
    return out
