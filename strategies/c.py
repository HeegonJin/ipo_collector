"""전략 C (매물 소화 후 회복): 확약 해제로 매물이 나온 뒤 가격이 안정되면 산다.

해제일은 상장일 + 확약 기간(1·3·6개월)이고, '매도 확인'은 거래량 급증으로 대신한다 (투자자별 매매는 수집하지 못함).
규칙 숫자는 config/strategy_C_v1.yaml. 관찰 기간이 막 끝난 날(최근 일봉이 관찰 마지막 날)에만 신호를 낸다.
"""
import statistics as st

from core.pit import PitReader
from core.schema import Status
from strategies.common import Signal, add_months, carried

NAME = "C_v1"


def _event(bars: list[dict], ipo_id: str, qty: float, shares: float, months: int, listing: str, e: dict) -> Signal | str:
    """한 해제 사건을 검사. 신호가 아니면 이유 문자열."""
    unlock = add_months(listing, months)
    idx_u = next((i for i, b in enumerate(bars) if b["date"] >= unlock), None)
    if idx_u is None:
        return f"{months}개월 해제일 미도래"
    w, nb = e["window_days"], e["volume_base_days"]
    if idx_u + w - 1 != len(bars) - 1:
        return f"{months}개월: 관찰 기간이 끝난 날이 아님"
    if idx_u < nb:
        return f"{months}개월: 해제 전 거래량 이력 부족"
    pct = qty / shares * 100
    if pct < e["min_unlock_pct"]:
        return f"{months}개월: 해제 물량 {pct:.1f}% 로 기준 미만"
    base = st.median([b["volume"] for b in bars[idx_u - nb:idx_u] if b["volume"] is not None] or [0])
    peak = max((b["volume"] or 0) for b in bars[idx_u:idx_u + w])
    if base <= 0:
        return f"{months}개월: 기준 거래량 계산 불가"
    if peak < base * e["volume_spike_x"]:
        return f"{months}개월: 거래량 급증 없음 ({peak / base:.1f}배)"
    tail = [b["close"] for b in bars[-e["stable_last_days"]:] if b["close"]]
    if len(tail) < e["stable_last_days"]:
        return f"{months}개월: 종가 자료 부족"
    spread = (max(tail) / min(tail) - 1) * 100
    if spread > e["stable_range_pct"]:
        return f"{months}개월: 종가 변동폭 {spread:.1f}% (불안정)"
    pre = bars[idx_u - 1]["close"]
    if not pre or bars[-1]["close"] < pre * e["min_close_vs_pre_unlock"]:
        return f"{months}개월: 해제 전 종가 대비 붕괴"
    return Signal(ipo_id, "매수", (f"해제 {months}개월", f"해제 물량 {pct:.1f}%, 거래량 {peak / base:.1f}배, 종가 변동폭 {spread:.1f}%"))


def evaluate(reader: PitReader, ipo_id: str, params: dict) -> Signal:
    code, listing, offer = carried(reader, ipo_id)
    if code is None or listing is None:
        return Signal(ipo_id, "관망", ("listing_date 또는 short_code 미확인",))
    keep = (code, listing, offer)
    e = params["entry"]
    bars = [b for b in reader.bars(code) if b["date"] >= listing]
    shares = next((b["shares"] for b in bars if b["date"] == listing and b.get("shares")), None)
    if not bars or shares is None:
        return Signal(ipo_id, "관망", ("상장주식수 미확인",), *keep)
    notes = []
    for months in e["periods_months"]:
        q = reader.fact(ipo_id, f"commit_{months}m_qty")
        if q.status is not Status.CONFIRMED or not q.value_num:
            notes.append(f"{months}개월 확약 수량 미확인·없음")
            continue
        r = _event(bars, ipo_id, q.value_num, shares, months, listing, e)
        if isinstance(r, Signal):
            return Signal(ipo_id, "매수", r.reasons, *keep)
        notes.append(r)
    return Signal(ipo_id, "관망", tuple(notes), *keep)
