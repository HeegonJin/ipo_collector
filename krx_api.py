"""
KRX Open API (openapi.krx.co.kr) 수집기.

필요한 서비스 이용신청 (마이페이지 → 서비스 이용신청, 승인 약 1일):
  - 주식: 코스닥 일별매매정보, 코넥스 일별매매정보, 코스닥 종목기본정보
  - 지수: KOSDAQ 시리즈 일별시세정보

날짜(basDd)마다 그날 거래된 '전 종목'이 한 번에 온다.
→ 나중에 상장폐지된 종목도 그 날짜 데이터에는 남아 있으므로 생존자 편향이 없다.

응답은 data/0_raw/krx/<서비스>/<YYYYMMDD>.json 으로 캐시한다. 이미 받은 날짜는 다시 호출하지 않는다.
엔드포인트 경로·필드명은 KRX Open API 서비스 명세서로 첫 실행 때 한 번 대조할 것 (VERIFY 표시).
"""
import json
import time
from datetime import date, datetime, timedelta

import requests

import config

BASE = "https://data-dbg.krx.co.kr/svc/apis"  # VERIFY
SERVICES = {
    "ksq_daily": "sto/ksq_bydd_trd",       # 코스닥 일별매매정보 (VERIFY)
    "knx_daily": "sto/knx_bydd_trd",       # 코넥스 일별매매정보 (VERIFY)
    "ksq_base": "sto/ksq_isu_base_info",   # 코스닥 종목기본정보 (VERIFY)
    "kosdaq_idx": "idx/kosdaq_dd_trd",     # KOSDAQ 시리즈 일별시세 (VERIFY)
}
CALL_INTERVAL_SEC = 0.3  # 과도한 호출 방지
RECENT_EMPTY_DAYS = 4    # 이 기간 안의 날짜가 빈 응답이면 캐시하지 않는다


def _cache_path(service: str, bas_dd: str):
    p = config.RAW / "krx" / service / f"{bas_dd}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def fetch(service: str, bas_dd: str, refresh: bool = False) -> list[dict]:
    """한 날짜의 응답 행 목록. 휴장일은 빈 목록."""
    path = _cache_path(service, bas_dd)
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))

    if not config.KRX_API_KEY:
        raise RuntimeError(".env 에 KRX_API_KEY 가 없습니다.")
    resp = requests.get(
        f"{BASE}/{SERVICES[service]}",
        headers={"AUTH_KEY": config.KRX_API_KEY},
        params={"basDd": bas_dd},
        timeout=20,
    )
    resp.raise_for_status()
    rows = resp.json().get("OutBlock_1", [])
    time.sleep(CALL_INTERVAL_SEC)
    # 당일·직전 자료는 아직 올라오지 않아 빈 응답일 수 있다 (2026-10-27 18:31 실측). 빈 응답을 캐시하면 영영 못 받는다.
    if not rows and bas_dd >= (date.today() - timedelta(days=RECENT_EMPTY_DAYS)).strftime("%Y%m%d"):
        return rows
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    _log(service, bas_dd, len(rows))
    return rows


def _log(service, bas_dd, n):
    config.META.mkdir(parents=True, exist_ok=True)
    with open(config.META / "collect_log.csv", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')},krx,{service},{bas_dd},{n}\n")


def daterange(start: str, end: str):
    d = datetime.strptime(start, "%Y%m%d").date()
    e = datetime.strptime(end, "%Y%m%d").date()
    while d <= e:
        if d.weekday() < 5:  # 주말 건너뜀 (공휴일은 빈 응답으로 처리)
            yield d.strftime("%Y%m%d")
        d += timedelta(days=1)


def collect(start: str, end: str):
    """코스닥 일별매매정보가 비어 있지 않은 날을 거래일로 보고, 그날 코넥스·지수도 받는다.
    지수 서비스가 승인 전(401)이면 한 번만 알리고 건너뛴다 (코스닥 기준선은 승인 뒤 다시 collect)."""
    trading_days, index_ok = [], True
    for d in daterange(start, end):
        if not fetch("ksq_daily", d):
            continue
        trading_days.append(d)
        fetch("knx_daily", d)
        if index_ok:
            try:
                fetch("kosdaq_idx", d)
            except requests.HTTPError as e:
                if e.response is None or e.response.status_code != 401:
                    raise
                index_ok = False
                print("[KRX] kosdaq_idx 401 (이용신청 미승인) — 지수 수집 건너뜀")
    print(f"[KRX] 거래일 {len(trading_days)}일 수집 완료 ({start}~{end})")
    return trading_days


if __name__ == "__main__":
    import sys
    end = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    collect(config.BUFFER_START, end)
