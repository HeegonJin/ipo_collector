"""정산: 판단 뒤의 실제 가격을 읽는 유일한 곳 (미래 데이터 접근 허용).

비용은 호출자가 넘긴다 (config/costs_v1.yaml 의 dict, 또는 같은 모양의 dict).
매도세 연도가 없으면 None 을 내지 않고 예외를 낸다.
"""
from dataclasses import dataclass

from decide.runner import Decision
from store.bars import INDEX_CODE


@dataclass(frozen=True)
class Settlement:
    ipo_id: str
    strategy: str
    entry_px: float | None
    exit_px: float | None
    gross_ret: float | None
    net_ret: float | None
    buy_at_limit_up: bool | None  # None = 공모가를 몰라 판정 불가
    bench_ret: float | None
    net_ret_status: str


def _by_date(bars: list[dict], code: str) -> dict:
    return {b["date"]: b for b in bars if b["short_code"] == code}


def settle(decision: Decision, bars: list[dict], costs: dict) -> Settlement:
    if decision.action != "매수":
        raise ValueError("매수 결정만 정산한다")
    d0 = decision.listing_date
    idx = _by_date(bars, INDEX_CODE)
    # 거래일 달력은 모든 bars 의 날짜. 지수가 없어도(승인 전) D1 을 찾을 수 있다.
    d1 = next((d for d in sorted({b["date"] for b in bars}) if d > d0), None)
    mine = _by_date(bars, decision.short_code)
    b0, b1 = mine.get(d0), mine.get(d1)
    c0 = b0["close"] if b0 else None
    o1 = b1["open"] if b1 else None
    offer = decision.offer_price

    limit_up = (c0 >= offer * 4 * 0.999) if (c0 and offer) else None
    gross = (o1 / c0 - 1) if c0 and o1 else None
    net, status = None, "계산 불가"
    if gross is not None:
        year = int(d0[:4])
        if year not in costs["kosdaq_sell_tax"]:
            raise ValueError(f"매도세율이 없는 연도: {year}")
        fee, slip, tax = costs["commission_per_side"], costs["slippage_per_side"], costs["kosdaq_sell_tax"][year]
        net = o1 * (1 - fee - slip - tax) / (c0 * (1 + fee + slip)) - 1
        status = "확인"
    i0, i1 = idx.get(d0), idx.get(d1)
    bench = (i1["open"] / i0["close"] - 1) if i0 and i1 and i0["close"] and i1["open"] else None
    return Settlement(decision.ipo_id, decision.strategy, c0, o1, gross, net, limit_up, bench, status)
