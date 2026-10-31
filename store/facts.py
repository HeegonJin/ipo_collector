"""레지스트리·공모 조건 CSV(build_dart_registry 출력) → Fact 목록. 판단 계층은 이 Fact 를 PitReader 로만 읽는다.

시점 규칙
  - offer_price: 확정 공시(offer_price_rcept)의 접수일 23:59:59 KST 부터 읽을 수 있다. 확인이 아니면 값 없이 미확인으로 둔다.
  - listing_date, short_code: KRX 종목기본정보 값이지만 언제부터 알려졌는지 실측하지 못했다.
    보수적으로 확정 공시 접수일부터 읽을 수 있다고 가정한다 (extractor 에 가정이라고 적는다).
    확정 공시가 없으면 시점을 정할 수 없으므로 사실을 만들지 않는다 (리더는 미확인을 돌려준다).
"""
import csv
from pathlib import Path

from core.schema import Fact, Phase, SourceType, Status
from core.tradingcal import dart_available_at

ASSUMPTION = "available_at=발행조건확정 접수일 (가정)"


def _read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def facts_from_demand_mart(demand_csv: Path) -> list[Fact]:
    """수요 마트(build_demand_mart) → 전략 B·C 입력 Fact. 교차 검증을 통과(확인)한 값만 확인으로 두고,
    나머지는 값 없이 미확인으로 둔다 (결측 ≠ 0). 시점은 해당 묶음을 가져온 공시의 접수일 23:59:59 KST."""
    out = []
    for r in _read(demand_csv):
        def add(var, value, status_ok, avail_col, rcept_col, unit):
            dt = r.get(avail_col)
            if not dt:
                return
            ok = status_ok and value not in (None, "")
            out.append(Fact(ipo_id=r["ipo_id"], var=var, unit=unit, available_at=dart_available_at(dt),
                            information_phase=Phase.PRE_LISTING, source_type=SourceType.DART, source_id=r.get(rcept_col, ""),
                            status=Status.CONFIRMED if ok else Status.UNVERIFIED,
                            value_num=float(str(value).replace(",", "")) if ok else None,
                            extractor="dart_demand"))
        add("demand_ratio", r.get("demand_ratio"), r.get("demand_status") == "확인", "demand_available_dt", "demand_rcept", "배")
        for p in ("1m", "3m", "6m"):
            add(f"commit_{p}_qty", r.get(f"commit_{p}_qty"), r.get("commit_status") == "확인", "commit_available_dt", "commit_rcept", "주")
    return out


def facts_from_registry(registry_csv: Path, terms_csv: Path) -> list[Fact]:
    rcept_dt = {t["rcept_no"]: t["rcept_dt"] for t in _read(terms_csv)}
    out = []
    for r in _read(registry_csv):
        final = r["offer_price_rcept"]
        # 실적보고서를 단독 채택한 경우 그 접수번호는 신고서 목록에 없으므로 레지스트리가 적어 둔 날짜를 우선한다
        dt = r.get("offer_price_available_dt") or rcept_dt.get(final)
        if r["in_trading_universe"] != "True" or not final or not dt:
            continue
        at = dart_available_at(dt)
        common = dict(ipo_id=r["ipo_id"], available_at=at, information_phase=Phase.PRE_LISTING)
        confirmed = r["offer_price_status"] == Status.CONFIRMED.value and r["offer_price_final"] != ""
        out.append(Fact(var="offer_price", unit="KRW", source_type=SourceType.DART, source_id=final,
                        status=Status.CONFIRMED if confirmed else Status.UNVERIFIED,
                        value_num=float(r["offer_price_final"]) if confirmed else None,
                        extractor="dart_terms.final_offer_terms", **common))
        if r["list_dd"]:
            out.append(Fact(var="listing_date", source_type=SourceType.KRX, source_id="ksq_isu_base_info",
                            status=Status.CONFIRMED, value_text=r["list_dd"], extractor=ASSUMPTION, **common))
        if r["stock_code"]:
            out.append(Fact(var="short_code", source_type=SourceType.KRX, source_id="ksq_isu_base_info",
                            status=Status.CONFIRMED, value_text=r["stock_code"], extractor=ASSUMPTION, **common))
    return out
