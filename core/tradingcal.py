"""거래일 계산과 available_at 규칙. 공휴일 목록은 호출자가 넘긴다 (없으면 주말만 건너뛴다)."""
from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9))


def next_business_day(d: date, holidays: frozenset = frozenset()) -> date:
    n = d + timedelta(days=1)
    while n.weekday() >= 5 or n in holidays:
        n += timedelta(days=1)
    return n


def krx_daily_available_at(trade_date: date, holidays: frozenset = frozenset(),
                           publish_time: time = time(8, 0)) -> datetime:
    """KRX 일별 자료는 D 다음 거래일 아침에 쓸 수 있다고 본다. (VERIFY: 실제 공개 시각을 실측해 바꿀 것)"""
    return datetime.combine(next_business_day(trade_date, holidays), publish_time, tzinfo=KST)


def dart_available_at(rcept_dt: str) -> datetime:
    """목록 API 는 날짜만 준다 → 접수일 23:59:59 로 보수적으로 둔다."""
    d = datetime.strptime(rcept_dt, "%Y%m%d").date()
    return datetime.combine(d, time(23, 59, 59), tzinfo=KST)
