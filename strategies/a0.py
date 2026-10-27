"""A0 기준선: 조건 없이 상장일(D0) 종가 매수 → 다음 거래일(D1) 시가 매도.

판단에 쓰는 값은 '오늘이 이 종목의 상장일인가' 뿐이다. 체결가와 상한가 여부는 판단이 아니라 정산(settle)에서 본다.
"""
from dataclasses import dataclass
from datetime import time

from core.pit import PitReader
from core.tradingcal import KST

NAME = "A0"
ENTRY_RULE = "D0_close"
EXIT_RULE = "D1_open"
DECISION_TIME = time(15, 20)  # 종가 단일가 직전. 이 시각 이후의 자료는 판단에 쓰지 않는다


@dataclass(frozen=True)
class Signal:
    ipo_id: str
    action: str  # 매수 | 관망
    reasons: tuple
    short_code: str | None = None
    listing_date: str | None = None
    offer_price: float | None = None


def evaluate(reader: PitReader, ipo_id: str) -> Signal:
    listing = reader.fact(ipo_id, "listing_date")
    code = reader.fact(ipo_id, "short_code")
    offer = reader.fact(ipo_id, "offer_price")
    if listing.value_text is None or code.value_text is None:
        return Signal(ipo_id, "관망", ("listing_date 또는 short_code 미확인",))
    carried = (code.value_text, listing.value_text, offer.value_num)
    today = reader.as_of.astimezone(KST)
    if listing.value_text != today.strftime("%Y%m%d"):
        return Signal(ipo_id, "관망", ("오늘이 상장일이 아님",), *carried)
    if today.time() < DECISION_TIME:
        return Signal(ipo_id, "관망", ("판단 시각 이전",), *carried)
    reasons = ("조건 없는 기준선",) + (() if offer.value_num is not None else ("offer_price 미확인",))
    return Signal(ipo_id, "매수", reasons, *carried)
