"""
OpenDART 보강: 신규상장 표본에 '공모 상장 여부'와 공시 원문 링크를 붙인다.

하는 일 (G1 범위)
  1) corpCode.xml 로 종목코드 → DART 고유번호 매핑
  2) 상장일 기준 12개월 전 ~ 상장일 사이 '발행공시(C)' 목록 조회
  3) 증권신고서(지분증권) / 발행조건확정 / 투자설명서 / 증권발행실적보고서 접수번호와 원문 링크 저장
     → 증권신고서가 없으면 '공모 없는 상장 의심'(재상장·분할재상장 등) → 표본 제외
  4) (선택) 증권신고서 주요정보 API로 공모가(모집가액) 교차검증

수요예측 경쟁률·확약 비율·유통가능 물량(S2~S4)은 공시 원문 표를 파싱해야 해서 G1+ 단계에서 한다.
여기서는 그 문서들의 접수번호·링크·접수일(=공개 시각)까지만 확보한다.
필드명·코드값은 OpenDART 개발가이드로 첫 실행 때 대조 (VERIFY 표시).
"""
import csv
import io
import json
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import config
from core import http

API ="https://opendart.fss.or.kr/api"
DOC_KEYWORDS = {
    "registration": "증권신고서(지분증권)",
    "final_terms": "발행조건확정",
    "prospectus": "투자설명서",
    "result_report": "증권발행실적보고서",
}


def _get(path, **params):
    params["crtfc_key"] = config.DART_API_KEY
    r = http.safe_get(f"{API}/{path}", params=params)
    time.sleep(0.2)
    return r


def corp_code_map():
    cache = config.RAW / "dart" / "corp_codes.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    z = zipfile.ZipFile(io.BytesIO(_get("corpCode.xml").content))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for el in root.iter("list"):
        stock = (el.findtext("stock_code") or "").strip()
        if stock:
            m[stock] = el.findtext("corp_code")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return m


def issuance_filings(corp_code, list_date):
    """상장일 이전 12개월의 발행공시 목록 (캐시)."""
    cache = config.RAW / "dart" / "filings" / f"{corp_code}_{list_date}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    end = datetime.strptime(list_date, "%Y%m%d")
    j = _get("list.json", corp_code=corp_code, bgn_de=(end - timedelta(days=365)).strftime("%Y%m%d"),
             end_de=list_date, pblntf_ty="C", page_count=100).json()  # C=발행공시 (VERIFY)
    rows = j.get("list", []) if j.get("status") == "000" else []
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def enrich(sample_csv):
    codes = corp_code_map()
    with open(sample_csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        if r["excluded"]:
            continue
        corp = codes.get(r["short_code"])
        if not corp:
            r["listing_type"] = "DART 고유번호 없음(확인)"
            continue
        filings = issuance_filings(corp, r["list_date"])
        found = {}
        for key, kw in DOC_KEYWORDS.items():
            hit = [x for x in filings if kw in x.get("report_nm", "")]
            if hit:
                latest = max(hit, key=lambda x: x["rcept_dt"])
                found[key] = f"{latest['rcept_dt']} https://dart.fss.or.kr/dsaf001/main.do?rcpNo={latest['rcept_no']}"
        r["dart_docs"] = " | ".join(f"{k}:{v}" for k, v in found.items())
        if "registration" in found or "result_report" in found:
            r["listing_type"] = "공모"
        else:
            r["listing_type"] = "공모 공시 없음"
            r["excluded"] = "공모 없는 상장 의심(재상장·분할 등)"

    out = sample_csv.with_name(sample_csv.stem + "_dart.csv")
    fields = list(rows[0].keys()) + (["dart_docs"] if "dart_docs" not in rows[0] else [])
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"[DART] {out}")
    return out


if __name__ == "__main__":
    import sys
    from pathlib import Path
    enrich(Path(sys.argv[1]))
