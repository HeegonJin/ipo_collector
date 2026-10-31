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
                       "high": num(r.get("TDD_HGPRC")), "low": num(r.get("TDD_LWPRC")),
                       "close": num(r.get("TDD_CLSPRC")), "volume": num(r.get("ACC_TRDVOL")),
                       "shares": num(r.get("LIST_SHRS")), "available_at": at}


def iter_index_bars(start: str, end: str):
    """코스닥 지수 일별 raw(kosdaq_idx)에서 '코스닥' 행만 bars 로 내보낸다. 파일이 없는 날(미수집·휴장)은 건너뛴다."""
    for d in daterange(start, end):
        p = config.RAW / "krx" / "kosdaq_idx" / f"{d}.json"
        if p.exists():
            yield from index_bars_from_krx_days({d: json.loads(p.read_text(encoding="utf-8"))})


def last_seen_dates(start: str, end: str) -> tuple[dict, str | None]:
    """종목별 일별 데이터 마지막 등장일과 데이터의 마지막 거래일. 마지막 거래일보다 일찍 사라진 종목은
    상장폐지·이전 등으로 더는 거래되지 않는 것이다 (생존자 편향 점검)."""
    seen, last_day = {}, None
    for d, rows in _raw_days(start, end):
        last_day = d
        for r in rows:
            seen[short_code(r)] = d
    return seen, last_day


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
