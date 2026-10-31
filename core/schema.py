"""공통 규격: status 5종, information_phase, 사실(Fact) 한 줄.

값을 모르면 value 를 비우고 status 로 이유를 남긴다. 0 으로 채우지 않는다.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Status(str, Enum):
    CONFIRMED = "확인"
    NOT_DISCLOSED = "미공시"
    NOT_APPLICABLE = "해당 없음"
    NOT_COMPUTABLE = "계산 불가"
    UNVERIFIED = "미확인"


class Phase(str, Enum):
    IPO_PRE = "IPO_PRE"
    PRE_LISTING = "PRE_LISTING"
    POST_LISTING = "POST_LISTING"


class SourceType(str, Enum):
    KRX = "KRX"
    DART = "DART"
    KIWOOM = "KIWOOM"
    DERIVED = "DERIVED"
    MANUAL = "MANUAL"   # 사람이 직접 입력한 값 (상장 예정일 등). 입력한 시각이 available_at 이다


@dataclass(frozen=True)
class Fact:
    ipo_id: str
    var: str
    status: Status
    available_at: datetime  # 타임존 포함(KST). 판단 시각 as_of 이전 것만 읽는다.
    information_phase: Phase
    source_type: SourceType
    source_id: str
    unit: str = ""
    value_num: float | None = None
    value_text: str | None = None
    event_time: datetime | None = None
    source_locator: str = ""
    version_seq: int = 0
    extractor: str = ""

    def __post_init__(self):
        if self.available_at.tzinfo is None:
            raise ValueError("available_at 에는 타임존이 필요합니다")
        has_value = self.value_num is not None or self.value_text is not None
        if self.status is Status.CONFIRMED and not has_value:
            raise ValueError("status=확인 인데 값이 없습니다")
        if self.status is not Status.CONFIRMED and has_value:
            raise ValueError(f"status={self.status.value} 인데 값이 있습니다 (결측은 값을 비워 둔다)")
