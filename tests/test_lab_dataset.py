"""전략 실험 앱의 종목별 특징 표: 공모 조건(상장 전 확정)과 상장일 값(look-ahead 주의)과 이후 시가들을 한 줄에 모은다."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.tradingcal import KST  # noqa: E402
from evaluate.outcomes import BarIndex  # noqa: E402
from lab.dataset import build_rows  # noqa: E402
from store.bars import CALENDAR_CODE, INDEX_CODE  # noqa: E402

AT = datetime(2026, 1, 1, tzinfo=KST)
DAYS = ["20250102", "20250103", "20250106", "20250107", "20250108", "20250109", "20250110", "20250113", "20250114"]
SPLITS = {"train": {"start": "2023-07-01", "end": "2025-06-30"}, "valid": {"start": "2025-07-01", "end": "2026-10-31"},
          "forward": {"start": "2026-11-16", "end": None}}


def bar(d, code, o, h, l, c):
    return {"date": d, "short_code": code, "open": o, "high": h, "low": l, "close": c, "available_at": AT}


def make_index(stock_days=DAYS, idx_closes=None):
    idx_closes = idx_closes or [700.0 + i for i in range(len(DAYS))]
    bars = [bar(d, CALENDAR_CODE, None, None, None, None) for d in DAYS]
    bars += [bar(d, INDEX_CODE, c, c, c, c) for d, c in zip(DAYS, idx_closes)]
    for i, d in enumerate(stock_days):
        bars.append(bar(d, "ABC", 10000 + 100 * i, 12000, 9000, 11000 + 100 * i))
    return BarIndex(bars)


def reg(**kw):
    base = {"ipo_id": "I1", "corp_name": "가나다", "stock_code": "ABC", "list_dd": "20250103", "offer_price_final": "10000"}
    base.update(kw)
    return base


def dem(**kw):
    base = {"ipo_id": "I1", "demand_ratio": "850.5", "demand_status": "확인", "retail_ratio": "1200.0", "final_commit_ratio": "0.2494",
            "alloc_status": "확인", "float_pct": "28.5", "float_status": "확인"}
    base.update(kw)
    return base


def one(registry=None, demand=None, index=None, splits=SPLITS):
    rows = build_rows([registry or reg()], index or make_index(), splits, {"I1": demand} if demand else None)
    assert len(rows) == 1
    return rows[0]


def test_demand_features_are_attached_only_when_they_passed_the_cross_checks():
    r = one(demand=dem())
    assert r["demand_ratio"] == pytest.approx(850.5) and r["retail_ratio"] == pytest.approx(1200.0)
    assert r["final_commit_pct"] == pytest.approx(24.94) and r["float_pct"] == pytest.approx(28.5)


def test_unconfirmed_or_missing_demand_values_are_none_not_zero():
    r = one(demand=dem(demand_status="미확인", alloc_status="미확인", float_status="미확인"))
    assert r["demand_ratio"] is None and r["retail_ratio"] is None and r["final_commit_pct"] is None and r["float_pct"] is None
    r = one()                                                                # 수요 마트에 종목이 없으면 전부 None
    assert all(r[k] is None for k in ("demand_ratio", "retail_ratio", "final_commit_pct", "float_pct"))
    assert one(demand=dem(demand_ratio=""))["demand_ratio"] is None


def test_offer_size_comes_from_the_given_map_and_is_none_when_unknown():
    assert "band_pos" not in one(demand=dem())                                 # 밴드 위치는 설계도 밖이라 뺀 채로
    rows = build_rows([reg()], make_index(), SPLITS, None, {"I1": 264.0})
    assert rows[0]["offer_amount_bil"] == 264.0
    assert one(demand=dem())["offer_amount_bil"] is None                        # 모르면 0 이 아니라 None


def test_open_vs_offer_is_the_listing_day_open_against_the_offer_price():
    assert one()["d0_open_vs_offer"] == pytest.approx((10100 / 10000 - 1) * 100)   # D0 = 두 번째 날, 시가 10100


def test_listing_day_values_are_percent_changes_with_the_index_from_the_previous_day():
    r = one(index=make_index())                                              # D0 = 20250103 (두 번째 날)
    assert r["d0_ret_vs_offer"] == pytest.approx((11100 / 10000 - 1) * 100)
    assert r["d0_drop_from_high"] == pytest.approx((11100 / 12000 - 1) * 100)
    assert r["d0_index_chg"] == pytest.approx((701 / 700 - 1) * 100)


def test_opens_after_listing_are_collected_by_trading_day_offset_with_gaps_as_none():
    r = one(index=make_index(stock_days=DAYS[:3] + DAYS[4:]))                # D3(20250107) 거래 없음
    assert r["open_d"][0] == 10100 and r["open_d"][1] == 10200
    assert r["open_d"][2] is None and r["open_d"][3] == 10300


def test_limit_up_close_is_flagged_with_the_same_rule_as_the_a0_baseline():
    r = one(index=BarIndex([bar(d, CALENDAR_CODE, None, None, None, None) for d in DAYS]
                           + [bar("20250103", "ABC", 40000, 40000, 40000, 40000)]))
    assert r["limit_up"] is True and one()["limit_up"] is False


def test_split_follows_the_listing_date():
    assert one()["split"] == "train"                                          # 2025-01-03 은 train(~2025-06-30)
    shifted = {"train": {"start": "2023-07-01", "end": "2025-01-02"}, "valid": {"start": "2025-01-03", "end": "2025-12-31"},
               "forward": {"start": "2026-11-16", "end": None}}
    assert one(splits=shifted)["split"] == "valid"
    gap = {"train": {"start": "2023-07-01", "end": "2024-12-31"}, "valid": {"start": "2025-02-01", "end": "2025-12-31"},
           "forward": {"start": "2026-11-16", "end": None}}
    assert one(splits=gap)["split"] == "none"                                 # 어느 구간에도 안 들어가면 쓰지 않는다


def test_raw_loader_keeps_the_daily_high_and_low(monkeypatch, tmp_path):
    import json

    import config
    from store.bars import iter_filtered_bars
    monkeypatch.setattr(config, "RAW", tmp_path)
    p = tmp_path / "krx" / "ksq_daily" / "20250103.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps([{"ISU_CD": "ABC", "TDD_OPNPRC": "10,000", "TDD_HGPRC": "12,000", "TDD_LWPRC": "9,000",
                              "TDD_CLSPRC": "11,000"}]), encoding="utf-8")
    (bar_,) = list(iter_filtered_bars("20250103", "20250103", {"ABC"}))
    assert (bar_["open"], bar_["high"], bar_["low"], bar_["close"]) == (10000.0, 12000.0, 9000.0, 11000.0)


def test_stock_without_a_listing_day_bar_is_skipped_not_zero_filled():
    idx = BarIndex([bar(d, CALENDAR_CODE, None, None, None, None) for d in DAYS])
    assert build_rows([reg()], idx, SPLITS) == []
