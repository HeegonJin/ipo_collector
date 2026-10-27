import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import settings  # noqa: E402


def test_costs_cover_sample_years():
    costs = settings.load_costs(2023, 2026)
    assert costs["commission_per_side"] > 0
    assert 0.002 in costs["slippage_sensitivity"]


def test_legacy_config_constants_come_from_the_costs_yaml():
    """비용 가정이 config.py 와 yaml 두 곳에 따로 있으면 결과 문서마다 가정이 어긋난다 → 출처는 yaml 하나."""
    import config
    costs = settings.load_costs(2023, 2026)
    assert config.COMMISSION_PER_SIDE == costs["commission_per_side"]
    assert config.SLIPPAGE_PER_SIDE == costs["slippage_per_side"]
    assert config.KOSDAQ_SELL_TAX == costs["kosdaq_sell_tax"]


def test_missing_tax_year_fails_loudly():
    with pytest.raises(ValueError, match="2027"):
        settings.load_costs(2023, 2027)


def test_missing_tax_year_in_copied_config(tmp_path):
    shutil.copytree(settings.CONFIG_DIR, tmp_path / "config")
    p = tmp_path / "config" / "costs_v1.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("  2025: 0.0015\n", ""), encoding="utf-8")
    with pytest.raises(ValueError, match="2025"):
        settings.load_costs(2023, 2026, config_dir=tmp_path / "config")


def test_splits_do_not_overlap():
    splits = settings.load_splits()
    assert str(splits["train"]["end"]) < str(splits["valid"]["start"])


def test_universe_excludes_spac_and_reit():
    uni = settings.load_universe()
    assert {"스팩", "리츠"} <= set(uni["exclude_name_keywords"])
