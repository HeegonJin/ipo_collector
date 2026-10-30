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
    base = {"ipo_id": "I1", "corp_name": "가나다", "stock_code": "ABC", "list_dd": "20250103",
            "offer_price_final": "10000", "band_low": "9000", "band_high": "10000"}
    base.update(kw)
    return base


def terms(**kw):
    base = {"ipo_id": "I1", "stock_cnt": "2000000", "rcept_no": "R1"}
    base.update(kw)
    return base


def one(registry=None, trm=None, index=None, splits=SPLITS):
    rows = build_rows([registry or reg()], [trm or terms()], index or make_index(), splits)
    assert len(rows) == 1
    return rows[0]


def test_band_position_is_zero_at_the_bottom_one_at_the_top_and_above_one_over_the_band():
    assert one(reg(offer_price_final="9000"))["band_pos"] == pytest.approx(0.0)
    assert one(reg(offer_price_final="10000"))["band_pos"] == pytest.approx(1.0)
    assert one(reg(offer_price_final="11000"))["band_pos"] == pytest.approx(2.0)
    assert one(reg(offer_price_final="8000"))["band_pos"] == pytest.approx(-1.0)


def test_degenerate_or_missing_band_gives_none_not_zero():
    assert one(reg(band_low="10000", band_high="10000"))["band_pos"] is None
    assert one(reg(band_low="", band_high=""))["band_pos"] is None


def test_offer_amount_is_shares_times_price_in_hundred_millions_and_none_when_shares_unknown():
    assert one()["offer_amount_bil"] == pytest.approx(200.0)                  # 2,000,000주 × 10,000원 = 200억
    assert one(trm=terms(stock_cnt=""))["offer_amount_bil"] is None


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
    assert build_rows([reg()], [terms()], idx, SPLITS) == []
