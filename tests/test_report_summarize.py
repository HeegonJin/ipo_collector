"""report.summarize: 하위 10% 는 선형보간 백분위수여야 한다 (표본이 작아도 최솟값으로 쏠리지 않게)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import report  # noqa: E402


def test_p10_of_ten_values_interpolates_between_the_two_lowest():
    s = report.summarize([float(v) for v in range(1, 11)])
    assert s["p10"] == pytest.approx(1.9)        # 기존 코드는 최솟값 1.0 을 냈다


def test_p10_of_two_values():
    assert report.summarize([0.0, 10.0])["p10"] == pytest.approx(1.0)


def test_p10_of_one_value_is_that_value():
    assert report.summarize([0.07])["p10"] == pytest.approx(0.07)


def test_p10_ignores_missing_values_and_keeps_n():
    s = report.summarize([None, 1.0, 2.0, None, 3.0])
    assert s["n"] == 3 and s["p10"] == pytest.approx(1.2)


def test_summarize_of_nothing_is_none_not_zero():
    assert report.summarize([None, None]) is None
