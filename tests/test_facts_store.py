import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_dart_registry as b  # noqa: E402
from core.schema import Status  # noqa: E402
from core.tradingcal import KST  # noqa: E402
from decide.runner import run_decision_point  # noqa: E402
from store.facts import facts_from_registry  # noqa: E402

IPO = "00534729_20260911000314"


def reg_row(**kw):
    base = {"ipo_id": IPO, "corp_code": "00534729", "stock_code": "195990", "corp_name": "디티에스",
            "first_rcept_no": "20260911000314", "first_rcept_dt": "20260911", "sale_method": "일반공모",
            "is_ipo_candidate": True, "list_dd": "20261023", "in_trading_universe": True, "n_filings": 3,
            "last_kind": "발행조건확정", "offer_price_final": 18500.0, "offer_price_status": "확인",
            "offer_price_rcept": "20261012000308", "band_low": 17000.0, "band_high": 18500.0, "offer_price_note": ""}
    base.update(kw)
    return base


def term_row(rcept, dt, kind):
    return {"ipo_id": IPO, "rcept_no": rcept, "rcept_dt": dt, "kind": kind, "available_at": b.available_at(dt)}


def write(tmp_path, reg, terms):
    rp = b.write([reg], b.REGISTRY_COLS, "reg.csv")
    tp = b.write(terms, b.TERMS_COLS, "terms.csv")
    return rp, tp


TERMS = [term_row("20260911000314", "20260911", "최초"), term_row("20261012000308", "20261012", "발행조건확정")]


def by_var(facts):
    return {f.var: f for f in facts}


def test_confirmed_offer_price_fact_is_available_after_the_confirming_filing(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "MART", tmp_path)
    rp, tp = write(tmp_path, reg_row(), TERMS)
    f = by_var(facts_from_registry(rp, tp))["offer_price"]
    assert f.status is Status.CONFIRMED and f.value_num == 18500.0
    assert f.available_at == datetime(2026, 10, 12, 23, 59, 59, tzinfo=KST)


def test_price_adopted_from_a_result_report_uses_its_own_available_date(tmp_path, monkeypatch):
    """실적보고서 단독 채택이면 그 접수번호는 신고서 목록(terms)에 없다 → 레지스트리의 available_dt 로 시점을 정한다."""
    import config
    monkeypatch.setattr(config, "MART", tmp_path)
    rp, tp = write(tmp_path, reg_row(offer_price_rcept="20261014000500", offer_price_available_dt="20261014"), TERMS)
    f = by_var(facts_from_registry(rp, tp))
    assert f["offer_price"].available_at == datetime(2026, 10, 14, 23, 59, 59, tzinfo=KST)
    assert f["listing_date"].available_at == datetime(2026, 10, 14, 23, 59, 59, tzinfo=KST)


def test_unverified_price_has_no_value_not_zero(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "MART", tmp_path)
    rp, tp = write(tmp_path, reg_row(offer_price_status="미확인", offer_price_final=None), TERMS)
    f = by_var(facts_from_registry(rp, tp))["offer_price"]
    assert f.status is Status.UNVERIFIED and f.value_num is None


def test_corps_outside_trading_universe_produce_no_facts(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "MART", tmp_path)
    rp, tp = write(tmp_path, reg_row(in_trading_universe=False), TERMS)
    assert facts_from_registry(rp, tp) == []


def test_without_confirming_filing_listing_facts_are_omitted(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "MART", tmp_path)
    rp, tp = write(tmp_path, reg_row(offer_price_rcept="", offer_price_final=None, offer_price_status="미확인"), TERMS)
    assert "listing_date" not in by_var(facts_from_registry(rp, tp))


def test_registry_facts_drive_the_a0_decision_at_listing_day(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "MART", tmp_path)
    rp, tp = write(tmp_path, reg_row(), TERMS)
    facts = facts_from_registry(rp, tp)
    d0 = datetime(2026, 10, 23, 15, 20, tzinfo=KST)
    (buy,) = run_decision_point(d0, [IPO], facts, [])
    assert buy.action == "매수" and buy.short_code == "195990" and buy.offer_price == 18500.0
    before_filing = datetime(2026, 10, 12, 12, 0, tzinfo=KST)
    (wait,) = run_decision_point(before_filing, [IPO], facts, [])
    assert wait.action == "관망"
