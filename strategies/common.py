"""전략 B·C 공통 도우미. 판단 계층이라 PitReader 로 읽은 값만 받는다 (파일·시계 접근 금지)."""
import calendar
from dataclasses import dataclass


@dataclass(frozen=True)
class Signal:
    ipo_id: str
    action: str  # 매수 | 관망
    reasons: tuple
    short_code: str | None = None
    listing_date: str | None = None
    offer_price: float | None = None


def add_months(yyyymmdd: str, months: int) -> str:
    """달력 기준 N개월 뒤 (말일을 넘으면 그 달 말일로)."""
    y, m, d = int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:])
    total = (y * 12 + (m - 1)) + months
    y2, m2 = divmod(total, 12)
    m2 += 1
    d2 = min(d, calendar.monthrange(y2, m2)[1])
    return f"{y2:04d}{m2:02d}{d2:02d}"


def carried(reader, ipo_id: str):
    """(short_code, listing_date, offer_price). 모르면 None."""
    code = reader.fact(ipo_id, "short_code").value_text
    listing = reader.fact(ipo_id, "listing_date").value_text
    offer = reader.fact(ipo_id, "offer_price").value_num
    return code, listing, offer
