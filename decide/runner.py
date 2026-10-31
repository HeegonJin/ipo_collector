"""판단 시점 실행기. 백테스트와 모의 운영이 이 함수를 그대로 공유한다.

여기서는 PitReader 만 읽는다. 파일·원본 bars·정산(evaluate) 모듈을 import 하지 않는다.
"""
from dataclasses import dataclass
from datetime import datetime

from core.pit import PitReader
from core.schema import Fact
from strategies import a0


@dataclass(frozen=True)
class Decision:
    ipo_id: str
    strategy: str
    as_of: datetime
    action: str
    entry_rule: str
    exit_rule: str
    reasons: tuple
    short_code: str | None
    listing_date: str | None
    offer_price: float | None
    weight: float | None = None      # L6 리스크 게이트가 정한 비중 (운용금 대비). A0 처럼 게이트를 거치지 않으면 None


def run_decision_point(as_of: datetime, ipo_ids: list[str], facts: list[Fact], bars: list[dict]) -> list[Decision]:
    reader = PitReader(facts, bars, as_of)
    out = []
    for ipo_id in ipo_ids:
        s = a0.evaluate(reader, ipo_id)
        out.append(Decision(ipo_id, a0.NAME, as_of, s.action, a0.ENTRY_RULE, a0.EXIT_RULE,
                            s.reasons, s.short_code, s.listing_date, s.offer_price))
    return out
