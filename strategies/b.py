"""전략 B (흥행 실패주 반등): 경쟁률이 낮았던 눌린 신규주를 코스닥이 저점에서 반등했을 때 산다.

규칙 숫자는 config/strategy_B_v1.yaml (호출자가 읽어서 params 로 넘긴다). 판단 시각 as_of 에 공개된 일봉까지만 본다.
신호가 나면 '다음 거래일 시가'에 사는 것이고, 한 종목에 한 번만 진입하는 것은 호출자(실행기·일일 작업)가 지킨다.
"""
from core.pit import PitReader
from core.schema import Status
from strategies.common import Signal, carried

NAME = "B_v1"
INDEX = "KOSDAQ"


def evaluate(reader: PitReader, ipo_id: str, params: dict) -> Signal:
    code, listing, offer = carried(reader, ipo_id)
    if code is None or listing is None:
        return Signal(ipo_id, "관망", ("listing_date 또는 short_code 미확인",))
    keep = (code, listing, offer)
    e = params["entry"]
    bars = reader.bars(code)
    after = [b for b in bars if b["date"] > listing]
    k = len(after)
    if not e["min_days_since_listing"] <= k <= e["max_days_since_listing"]:
        return Signal(ipo_id, "관망", (f"상장 후 {k}거래일: 범위 밖",), *keep)
    idx = reader.bars(INDEX)
    if not idx or after[-1]["date"] != idx[-1]["date"]:
        return Signal(ipo_id, "관망", ("최근 거래일에 거래 없음 또는 지수 자료 없음",), *keep)
    dem = reader.fact(ipo_id, "demand_ratio")
    if dem.status is not Status.CONFIRMED:
        return Signal(ipo_id, "관망", ("수요예측 경쟁률 미확인",), *keep)
    if dem.value_num > e["max_demand_ratio"]:
        return Signal(ipo_id, "관망", (f"경쟁률 {dem.value_num:.0f}배: 흥행 실패 기준 초과",), *keep)
    if offer is None:
        return Signal(ipo_id, "관망", ("offer_price 미확인",), *keep)
    last = after[-1]["close"]
    if last is None or last > offer * e["max_close_vs_offer"]:
        return Signal(ipo_id, "관망", ("종가가 공모가 기준 위",), *keep)
    n = e["market_lookback_days"]
    closes = [b["close"] for b in idx[-n:] if b["close"]]
    if len(closes) < n:
        return Signal(ipo_id, "관망", ("코스닥 지수 이력 부족",), *keep)
    rebound = (closes[-1] / min(closes) - 1) * 100
    if rebound < e["market_rebound_pct"]:
        return Signal(ipo_id, "관망", (f"코스닥 저점 대비 {rebound:.1f}%: 반등 기준 미달",), *keep)
    return Signal(ipo_id, "매수", (f"경쟁률 {dem.value_num:.0f}배, 종가 공모가 이하, 코스닥 저점 대비 +{rebound:.1f}%",), *keep)
