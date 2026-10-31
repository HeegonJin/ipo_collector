"""정산: 판단 뒤의 실제 가격을 읽는 유일한 곳 (미래 데이터 접근 허용).

비용은 호출자가 넘긴다 (config/costs_v1.yaml 의 dict, 또는 같은 모양의 dict).
매도세 연도가 없으면 None 을 내지 않고 예외를 낸다.
"""
import bisect
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
    # 청산 가격이 없을 때(생존자 편향의 통로)의 사유와 민감도 값. net_ret 은 None 으로 두되 조용히 사라지지 않게 한다.
    exit_kind: str = "정상"                     # 정상 | 거래정지 | 폐지 | 미도래(청산일이 아직 오지 않음)
    net_ret_last_close: float | None = None     # 거래정지: 재개 후 첫 시가 / 폐지: 마지막 종가로 청산했다면
    net_ret_wipeout: float | None = None        # 전손(-100%) 가정
    exit_date: str | None = None                # 가변 청산(전략 B·C)의 실제 청산일. A0 는 비워 둔다
    exit_reason: str | None = None              # 기간 | 손절 | 익절


class BarIndex:
    """bars 를 한 번만 훑어 종목별 {날짜: bar} 와 정렬된 거래일 달력을 만든다 (정산마다 전체를 다시 훑지 않도록).
    거래일 달력은 모든 bars 의 날짜 합집합이라 지수가 없어도(승인 전) D1 을 찾을 수 있다."""

    def __init__(self, bars: list[dict]):
        self.bars = bars
        self.by_code: dict[str, dict[str, dict]] = {}
        for b in bars:
            self.by_code.setdefault(b["short_code"], {})[b["date"]] = b
        self.calendar = sorted({b["date"] for b in bars})

    def code(self, short_code: str) -> dict:
        return self.by_code.get(short_code, {})

    def next_day(self, d: str):
        i = bisect.bisect_right(self.calendar, d)
        return self.calendar[i] if i < len(self.calendar) else None

    def prev_day(self, d: str):
        i = bisect.bisect_left(self.calendar, d)
        return self.calendar[i - 1] if i > 0 else None

    def day_after(self, d: str, k: int):
        """거래일 달력에서 d 로부터 k 거래일 뒤 (k=0 이면 d 자신). 달력 끝을 넘으면 None."""
        i = bisect.bisect_left(self.calendar, d)
        if i >= len(self.calendar) or self.calendar[i] != d:
            return None
        return self.calendar[i + k] if i + k < len(self.calendar) else None


def _net(exit_px: float, c0: float, rates: tuple) -> float:
    fee, slip, tax = rates
    return exit_px * (1 - fee - slip - tax) / (c0 * (1 + fee + slip)) - 1


def _exit_fallbacks(mine: dict, d1, d0: str, c0, rates):
    """D1 시가가 없을 때의 사유와 민감도. 이후 거래가 있으면 거래정지(재개 후 첫 시가), 없으면 폐지(마지막 종가)."""
    if c0 is None:
        return "정상", None, None
    if d1 is None:
        return "미도래", None, None             # 청산일이 아직 오지 않았다: 폐지가 아니다
    later = sorted(d for d in mine if d > d0)
    if later:
        return "거래정지", _net(mine[later[0]]["open"], c0, rates), -1.0
    return "폐지", _net(mine[d0]["close"], c0, rates), -1.0


def settle(decision: Decision, bars, costs: dict) -> Settlement:
    """bars 는 list[dict] 또는 미리 만든 BarIndex. 같은 bars 로 여러 번 정산할 때는 BarIndex 를 넘긴다.

    청산 가격(D1 시가)이 없으면 net_ret 은 None(계산 불가)으로 두되, 사유(exit_kind)와 마지막 종가·전손 가정 값을 함께 남긴다.
    통계에서 조용히 빠지면 폐지·정지 종목이 사라져 성과가 좋아 보이는 생존자 편향이 생기기 때문이다."""
    if decision.action != "매수":
        raise ValueError("매수 결정만 정산한다")
    index = bars if isinstance(bars, BarIndex) else BarIndex(bars)
    d0 = decision.listing_date
    idx = index.code(INDEX_CODE)
    d1 = index.next_day(d0)
    mine = index.code(decision.short_code)
    b0, b1 = mine.get(d0), mine.get(d1)
    c0 = b0["close"] if b0 else None
    o1 = b1["open"] if b1 else None
    offer = decision.offer_price

    limit_up = (c0 >= offer * 4 * 0.999) if (c0 and offer) else None
    gross = (o1 / c0 - 1) if c0 and o1 else None
    net, status, kind, last_close, wipeout = None, "계산 불가", "정상", None, None
    year = int(d0[:4])
    if gross is not None or c0:
        if year not in costs["kosdaq_sell_tax"]:
            raise ValueError(f"매도세율이 없는 연도: {year}")
    rates = (costs["commission_per_side"], costs["slippage_per_side"], costs["kosdaq_sell_tax"].get(year))
    if gross is not None:
        net, status = _net(o1, c0, rates), "확인"
    else:
        kind, last_close, wipeout = _exit_fallbacks(mine, d1, d0, c0, rates)
    i0, i1 = idx.get(d0), idx.get(d1)
    bench = (i1["open"] / i0["close"] - 1) if i0 and i1 and i0["close"] and i1["open"] else None
    return Settlement(decision.ipo_id, decision.strategy, c0, o1, gross, net, limit_up, bench, status,
                      kind, last_close, wipeout)
