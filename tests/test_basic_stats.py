"""기초 통계: 구간 분류와 기간 수익률 계산 (합성 시세, 키 없이)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluate import basic_stats as bs  # noqa: E402
from evaluate.outcomes import BarIndex  # noqa: E402
from store.bars import CALENDAR_CODE, INDEX_CODE  # noqa: E402
from test_lab_dataset import SPLITS, bar, reg  # noqa: E402

DAYS = [f"2025{m:02d}{d:02d}" for m, d in [(1, 2), (1, 3), (1, 6), (1, 7), (1, 8), (1, 9), (1, 10), (1, 13)]]


def index(stock_closes, idx_closes):
    bars = [bar(d, CALENDAR_CODE, None, None, None, None) for d in DAYS]
    bars += [bar(d, INDEX_CODE, c, c, c, c) for d, c in zip(DAYS, idx_closes)]
    bars += [bar(d, "ABC", c, c * 1.02, c * 0.98, c) for d, c in zip(DAYS, stock_closes)]
    return BarIndex(bars)


def test_first_day_type_matrix_follows_open_vs_offer_and_close_vs_high():
    assert bs.first_day_type(12000, 14900, 15000, 10000) == 1      # 시초>공모가, 종가가 고점 근처
    assert bs.first_day_type(12000, 11000, 15000, 10000) == 2      # 고점에서 -26% 밀림
    assert bs.first_day_type(9000, 9900, 10000, 10000) == 3
    assert bs.first_day_type(9000, 8000, 10000, 10000) == 4
    assert bs.first_day_type(None, 8000, 10000, 10000) is None     # 모르면 분류하지 않는다


def test_offer_size_uses_the_last_share_count_filed_before_listing():
    terms = [{"rcept_dt": "20241201", "stock_cnt": "900000"}, {"rcept_dt": "20241220", "stock_cnt": "1,000,000"},
             {"rcept_dt": "20250120", "stock_cnt": "5000000"}]        # 상장 뒤 공시는 쓰지 않는다
    assert bs.offer_size_bil(reg(list_dd="20250103"), terms) == pytest.approx(10000 * 1_000_000 / 1e8)
    assert bs.offer_size_bil(reg(list_dd="20250103"), []) is None


def test_period_returns_are_from_the_listing_close_and_excess_subtracts_the_index():
    idx = index([100.0] + [110.0] * 7, [1000.0] * 8)                  # D0 = 두 번째 날, 종가 110
    rows = bs.build_rows([reg(offer_price_final="100")], {}, {}, idx, SPLITS)
    m = rows[0]["measures"]
    assert m[bs.MEASURES[0]] == pytest.approx(10.0)                    # 110/100 - 1
    assert m["1주(D+5)"] == pytest.approx(0.0) and m["1주(D+5)|초과"] == pytest.approx(0.0)
    assert m["1개월(D+21)"] is None and m["1개월(D+21)|초과"] is None  # 거래일이 모자라면 비운다 (0 이 아님)


def test_valid_split_is_never_opened():
    with pytest.raises(ValueError):
        bs.run("20261029", split="valid")


def test_small_groups_show_no_numbers():
    assert bs.cell([1.0] * (bs.MIN_N - 1)).startswith("표본 부족")
    assert bs.cell([1.0] * bs.MIN_N).startswith("+1.0%")
    assert bs.cell([]) == "-"
