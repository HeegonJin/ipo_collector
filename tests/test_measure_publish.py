"""KRX 일별 자료 공개 시각 측정 스크립트의 순수 함수: 전 영업일 계산과 '처음 공개된 시각' 판정."""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.measure_krx_publish import first_seen, previous_business_day  # noqa: E402

T0 = datetime(2026, 11, 3, 7, 0)


def probes(*rows_by_minute):
    return [{"probed_at": T0 + timedelta(minutes=m), "rows": r} for m, r in rows_by_minute]


def test_previous_business_day_skips_weekends_and_holidays():
    assert previous_business_day(date(2026, 11, 3)) == date(2026, 11, 2)       # 화 → 월
    assert previous_business_day(date(2026, 11, 2)) == date(2026, 10, 30)      # 월 → 금
    assert previous_business_day(date(2026, 11, 3), holidays={date(2026, 11, 2)}) == date(2026, 10, 30)


def test_first_seen_is_bounded_when_the_data_appears_after_an_empty_probe():
    got = first_seen(probes((0, 0), (2, 0), (4, 1824), (6, 1824)))
    assert got["status"] == "측정됨" and got["after"] == T0 + timedelta(minutes=2) and got["at"] == T0 + timedelta(minutes=4)


def test_data_already_present_at_the_first_probe_cannot_be_timed():
    got = first_seen(probes((0, 1824), (2, 1824)))
    assert got["status"] == "측정 불가(시작 시점에 이미 공개)" and got["at"] is None


def test_never_published_before_the_deadline():
    got = first_seen(probes((0, 0), (2, 0)))
    assert got["status"] == "마감까지 미공개(휴장일일 수 있음)" and got["at"] is None


def test_no_probes_is_not_a_measurement():
    assert first_seen([])["status"] == "조회 없음"
