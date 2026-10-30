"""학습/검증/전진 구간(config/splits_v1.yaml)을 평가에 적용한다. 검증 구간은 한 번만 열고, 열 때마다 기록한다."""
import csv
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluate.splits import in_split, open_split, window  # noqa: E402

SPLITS = {"train": {"start": "2023-07-01", "end": "2025-06-30"},
          "valid": {"start": "2025-07-01", "end": "2026-10-31"},
          "forward": {"start": "2026-11-16", "end": None}}


def test_window_returns_compact_dates_and_open_end_for_forward():
    assert window("train", SPLITS) == ("20230701", "20250630")
    assert window("forward", SPLITS) == ("20261116", "99991231")
    assert window("all", SPLITS) == ("00000101", "99991231")


def test_in_split_is_inclusive_on_both_ends():
    assert in_split("20230701", "train", SPLITS) and in_split("20250630", "train", SPLITS)
    assert not in_split("20250701", "train", SPLITS) and not in_split("20230630", "train", SPLITS)
    assert in_split("20261201", "forward", SPLITS) and in_split("20300101", "forward", SPLITS)
    assert in_split("20240101", "all", SPLITS)


def test_unknown_split_name_is_an_error():
    with pytest.raises(ValueError):
        window("test", SPLITS)


def test_opening_train_or_all_is_not_logged(tmp_path):
    log = tmp_path / "validation_runs.csv"
    assert open_split("train", log, "a0", datetime(2026, 10, 30, 9, 0)) == {"opened_before": 0, "warning": ""}
    open_split("all", log, "a0", datetime(2026, 10, 30, 9, 0))
    assert not log.exists()


def test_validation_split_is_logged_and_the_second_opening_warns(tmp_path):
    log = tmp_path / "validation_runs.csv"
    first = open_split("valid", log, "a0 v1", datetime(2026, 10, 30, 9, 0))
    second = open_split("valid", log, "a0 v2", datetime(2026, 10, 31, 9, 0))
    assert first == {"opened_before": 0, "warning": ""}
    assert second["opened_before"] == 1 and "2번째" in second["warning"] and "a0 v1" in second["warning"]
    rows = list(csv.DictReader(open(log, encoding="utf-8-sig")))
    assert [r["tag"] for r in rows] == ["a0 v1", "a0 v2"] and rows[0]["split"] == "valid"
