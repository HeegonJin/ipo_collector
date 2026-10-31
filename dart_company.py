"""DART 기업개황(company.json)의 업종코드(induty_code, 한국표준산업분류)를 회사별로 받아 캐시한다.

업종지수 강도(lab/features.py)에서 종목을 KRX 업종지수에 잇는 데만 쓴다. 업종코드는 회사의 현재 값이라 상장 후 바뀌었을 수 있다
(이력은 제공되지 않는다 — 한계로 화면·문서에 적는다).
캐시: data/0_raw/dart/company/<corp_code>.json (한 번 받으면 다시 받지 않는다)

  python dart_company.py            # 레지스트리의 모든 회사 (유니버스 + 2023-07 이전)
"""
import csv
import json
import sys
import time

import config
from core import http, ids

API = "https://opendart.fss.or.kr/api"
DIR = config.RAW / "dart" / "company"


def fetch(corp_code: str, refresh: bool = False) -> dict:
    corp_code = ids.safe_corp_code(corp_code)
    path = DIR / f"{corp_code}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    r = http.safe_get(f"{API}/company.json", params={"crtfc_key": config.DART_API_KEY, "corp_code": corp_code})
    j = r.json()
    if j.get("status") != "000":
        raise RuntimeError(f"DART company 오류 {j.get('status')} ({corp_code}): {j.get('message')}")
    DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.2)
    return j


def induty_codes() -> dict:
    """{corp_code: induty_code} — 받아 둔 것만. 없으면 키가 없다 (결측 ≠ 0)."""
    out = {}
    for p in DIR.glob("*.json") if DIR.exists() else []:
        code = json.loads(p.read_text(encoding="utf-8")).get("induty_code")
        if code:
            out[p.stem] = str(code)
    return out


def collect_all() -> int:
    with open(config.MART / "dart_ipo_registry.csv", encoding="utf-8-sig", newline="") as f:
        corps = sorted({r["corp_code"] for r in csv.DictReader(f) if r["corp_code"]})
    n = 0
    for c in corps:
        had = (DIR / f"{c}.json").exists()
        fetch(c)
        n += 0 if had else 1
    return n


if __name__ == "__main__":
    print(f"[DART] 기업개황 새로 받음 {collect_all()}건, 업종코드 보유 {len(induty_codes())}건")
