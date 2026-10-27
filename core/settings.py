"""config/*.yaml 로더. 필요한 값이 빠져 있으면 조용히 None 을 내지 않고 바로 실패한다."""
from datetime import date
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load(name: str, config_dir: Path | None = None) -> dict:
    path = (config_dir or CONFIG_DIR) / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_costs(first_year: int, last_year: int, config_dir: Path | None = None) -> dict:
    """표본 기간 [first_year, last_year] 의 매도세가 모두 있어야 한다."""
    costs = _load("costs_v1.yaml", config_dir)
    missing = [y for y in range(first_year, last_year + 1) if y not in costs["kosdaq_sell_tax"]]
    if missing:
        raise ValueError(f"costs_v1.yaml 에 매도세율이 없는 연도: {missing}")
    return costs


def load_splits(config_dir: Path | None = None) -> dict:
    splits = _load("splits_v1.yaml", config_dir)
    for name in ("train", "valid", "forward"):
        if name not in splits:
            raise ValueError(f"splits_v1.yaml 에 {name} 구간이 없습니다")
    train_end = date.fromisoformat(str(splits["train"]["end"]))
    valid_start = date.fromisoformat(str(splits["valid"]["start"]))
    if valid_start <= train_end:
        raise ValueError("valid 구간이 train 구간과 겹칩니다")
    return splits


def load_universe(config_dir: Path | None = None) -> dict:
    return _load("universe_v1.yaml", config_dir)
