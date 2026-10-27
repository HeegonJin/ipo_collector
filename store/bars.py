"""KRX 날짜별 응답 → available_at 이 붙은 bars. (L2: 0_raw → 1_clean 방향의 변환)"""
import json
from datetime import datetime

import config
from build_sample import num, short_code
from core.tradingcal import krx_daily_available_at
from krx_api import daterange

INDEX_CODE = "KOSDAQ"
CALENDAR_CODE = "_CAL"  # 거래일 표지. 종목 bars 를 걸러도 달력(D1 찾기)이 유지되게 한다


def _raw_days(start: str, end: str):
    for d in daterange(start, end):
        p = config.RAW / "krx" / "ksq_daily" / f"{d}.json"
        if p.exists():
            rows = json.loads(p.read_text(encoding="utf-8"))
            if rows:
                yield d, rows


def iter_filtered_bars(start: str, end: str, codes: set):
    """코스닥 일별 raw 에서 지정한 종목 코드의 bars 만 하나씩 내보낸다 (전체를 메모리에 올리지 않는다)."""
    for d, rows in _raw_days(start, end):
        at = krx_daily_available_at(_day(d))
        for r in rows:
            code = short_code(r)
            if code in codes:
                yield {"date": d, "short_code": code, "open": num(r.get("TDD_OPNPRC")),
                       "close": num(r.get("TDD_CLSPRC")), "available_at": at}


def calendar_bars(start: str, end: str) -> list[dict]:
    return [{"date": d, "short_code": CALENDAR_CODE, "open": None, "close": None,
             "available_at": krx_daily_available_at(_day(d))} for d, _ in _raw_days(start, end)]


def _day(d: str):
    return datetime.strptime(d, "%Y%m%d").date()


def bars_from_krx_days(ksq_days: dict) -> list[dict]:
    out = []
    for d, rows in ksq_days.items():
        at = krx_daily_available_at(_day(d))
        for r in rows:
            out.append({"date": d, "short_code": short_code(r), "open": num(r.get("TDD_OPNPRC")),
                        "close": num(r.get("TDD_CLSPRC")), "available_at": at})
    return out


def index_bars_from_krx_days(idx_days: dict) -> list[dict]:
    out = []
    for d, rows in idx_days.items():
        at = krx_daily_available_at(_day(d))
        for r in rows:
            if r.get("IDX_NM") == "코스닥":
                out.append({"date": d, "short_code": INDEX_CODE, "open": num(r.get("OPNPRC_IDX")),
                            "close": num(r.get("CLSPRC_IDX")), "available_at": at})
    return out
