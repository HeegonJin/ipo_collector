"""
PIT 리더: 판단 시각 as_of 에 이미 공개된 값만 돌려주는 유일한 읽기 통로.

  - 값이 없으면 0 이 아니라 status=미확인 인 FactValue 를 돌려준다.
  - 같은 변수의 정정본이 여러 개면 as_of 이전에 공개된 것 중 가장 늦은 버전을 고른다.
"""
from dataclasses import dataclass
from datetime import datetime

from core.schema import Fact, Status


@dataclass(frozen=True)
class FactValue:
    ipo_id: str
    var: str
    status: Status
    value_num: float | None = None
    value_text: str | None = None
    available_at: datetime | None = None
    source_id: str = ""


class PitReader:
    def __init__(self, facts: list[Fact], bars: list[dict], as_of: datetime):
        if as_of.tzinfo is None:
            raise ValueError("as_of 에는 타임존이 필요합니다")
        self.as_of = as_of
        self._facts = [f for f in facts if f.available_at <= as_of]
        self._bars = [b for b in bars if b["available_at"] <= as_of]

    def fact(self, ipo_id: str, var: str) -> FactValue:
        hits = [f for f in self._facts if f.ipo_id == ipo_id and f.var == var]
        if not hits:
            return FactValue(ipo_id, var, Status.UNVERIFIED)
        f = max(hits, key=lambda x: (x.available_at, x.version_seq))
        return FactValue(f.ipo_id, f.var, f.status, f.value_num, f.value_text, f.available_at, f.source_id)

    def bars(self, short_code: str, n: int | None = None) -> list[dict]:
        rows = sorted((b for b in self._bars if b["short_code"] == short_code), key=lambda b: b["date"])
        return rows[-n:] if n else rows
