"""KRX 일별 자료(코스닥 일별매매정보)가 전 영업일 자료를 언제 공개하는지 측정한다.

공식 약관·명세에는 공개 시각 조항이 없다 (2026-10-30 확인). 비공식 자료는 '기준일 다음 날 08시 전후'라고 한다.
이 스크립트는 오늘 아침 07:00 부터 마감 시각까지 몇 분 간격으로 전 영업일 자료를 조회해, 처음 비어 있지 않게 된
시각을 data/_meta/krx_publish_log.csv 에 남긴다.

  python tools/measure_krx_publish.py [--deadline 10:00] [--interval 120]

주의: 스크립트가 시작될 때 이미 자료가 있으면 공개 시각을 알 수 없으므로 '측정 불가'로 기록한다 (거짓 시각을 남기지 않는다).
호출량: 2분 간격 3시간이면 약 90회로 하루 한도(10,000회)에 영향이 없다.
"""
import argparse
import csv
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import krx_api  # noqa: E402

LOG_COLS = ["probed_at", "base_date", "rows", "note"]


def previous_business_day(today: date, holidays=frozenset()) -> date:
    d = today - timedelta(days=1)
    while d.weekday() >= 5 or d in holidays:
        d -= timedelta(days=1)
    return d


def first_seen(probes: list[dict]) -> dict:
    """probes: [{'probed_at': datetime, 'rows': int}, ...] (시간순). 처음 공개된 시각을 판정한다.
    첫 조회부터 자료가 있었으면 공개 시각을 알 수 없다. 비어 있다가 생겼으면 (직전 빈 조회, 처음 찬 조회] 구간에 공개된 것이다."""
    if not probes:
        return {"status": "조회 없음", "after": None, "at": None}
    if probes[0]["rows"] > 0:
        return {"status": "측정 불가(시작 시점에 이미 공개)", "after": None, "at": None}
    for prev, cur in zip(probes, probes[1:]):
        if cur["rows"] > 0:
            return {"status": "측정됨", "after": prev["probed_at"], "at": cur["probed_at"]}
    return {"status": "마감까지 미공개(휴장일일 수 있음)", "after": None, "at": None}


def _append(row: dict) -> None:
    path = config.META / "krx_publish_log.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        if new:
            w.writeheader()
        w.writerow(row)


def run(deadline: str = "10:00", interval: int = 120) -> dict:
    base = previous_business_day(date.today()).strftime("%Y%m%d")
    end = datetime.combine(date.today(), datetime.strptime(deadline, "%H:%M").time())
    probes = []
    while True:
        now = datetime.now()
        rows = len(krx_api.fetch("ksq_daily", base, refresh=True))   # refresh: 캐시가 아니라 지금 서버 상태를 본다
        probes.append({"probed_at": now, "rows": rows})
        _append({"probed_at": now.isoformat(timespec="seconds"), "base_date": base, "rows": rows, "note": ""})
        if rows > 0 or datetime.now() >= end:
            break
        time.sleep(interval)
    result = first_seen(probes)
    _append({"probed_at": datetime.now().isoformat(timespec="seconds"), "base_date": base, "rows": probes[-1]["rows"],
             "note": f"{result['status']} | 직전 빈 조회 {result['after']} | 첫 공개 확인 {result['at']}"})
    return {"base_date": base, **result}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--deadline", default="10:00")
    ap.add_argument("--interval", type=int, default=120)
    a = ap.parse_args()
    print(run(a.deadline, a.interval))
