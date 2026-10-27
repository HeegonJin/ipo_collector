"""A0 백테스트 드라이버: 상장일 15:20 마다 run_decision_point 를 부르고, 매수 결정만 settle 한다.

판단 시점 목록(L0 일정)은 listing_date 사실에서 만든다. 판단 자체는 PitReader 를 통해서만 이뤄진다.
"""
from collections import defaultdict
from datetime import datetime

from core.schema import Fact
from core.tradingcal import KST
from decide.runner import Decision, run_decision_point
from evaluate.outcomes import BarIndex, Settlement, settle
from strategies.a0 import DECISION_TIME


def decision_points(ipo_ids: list[str], facts: list[Fact]) -> dict:
    listing = {}
    for f in facts:
        if f.var == "listing_date" and f.ipo_id in ipo_ids and f.value_text:
            listing[f.ipo_id] = f.value_text
    points = defaultdict(list)
    for ipo_id, d in listing.items():
        as_of = datetime.strptime(d, "%Y%m%d").replace(hour=DECISION_TIME.hour, minute=DECISION_TIME.minute, tzinfo=KST)
        points[as_of].append(ipo_id)
    return dict(sorted(points.items()))


def run_a0(ipo_ids: list[str], facts: list[Fact], bars, costs: dict) -> list[tuple[Decision, Settlement]]:
    """bars 는 list[dict] 또는 BarIndex. 색인은 백테스트 한 번에 한 번만 만든다 (여러 번 돌릴 때는 BarIndex 를 넘긴다)."""
    index = bars if isinstance(bars, BarIndex) else BarIndex(bars)
    out = []
    for as_of, ids in decision_points(ipo_ids, facts).items():
        for d in run_decision_point(as_of, ids, facts, index.bars):
            if d.action == "매수":
                out.append((d, settle(d, index, costs)))
    return out
