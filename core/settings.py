"""config/*.yaml 로더. 필요한 값이 빠져 있으면 조용히 None 을 내지 않고 바로 실패한다."""
import hashlib
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


def load_lab(config_dir: Path | None = None) -> dict:
    """전략 실험 앱의 과적합 방지 장치 기준값 (최소 표본 수, 검증 구간 확인 문구, 시도 횟수 경고 기준)."""
    lab = _load("lab_v1.yaml", config_dir)
    for key in ("min_n", "confirm_phrase", "trials_warn_at"):
        if key not in lab:
            raise ValueError(f"lab_v1.yaml 에 {key} 가 없습니다")
    return lab


def load_strategy(name: str, config_dir: Path | None = None) -> dict:
    """전략 규칙 파일 config/strategy_<name>.yaml (예: 'B_v1'). 진입·청산 숫자가 모두 있어야 한다."""
    if not name.replace("_", "").isalnum():
        raise ValueError(f"잘못된 전략 이름: {name!r}")
    cfg = _load(f"strategy_{name}.yaml", config_dir)
    for key in ("entry", "exit"):
        if key not in cfg:
            raise ValueError(f"strategy_{name}.yaml 에 {key} 가 없습니다")
    for key in ("hold_days", "stop_loss_pct", "take_profit_pct"):
        if key not in cfg["exit"]:
            raise ValueError(f"strategy_{name}.yaml 의 exit 에 {key} 가 없습니다")
    return cfg


def load_universe(config_dir: Path | None = None) -> dict:
    return _load("universe_v1.yaml", config_dir)


def load_risk(config_dir: Path | None = None) -> dict:
    cfg = _load("risk_v1.yaml", config_dir)
    for key in ("paper_capital_krw", "weight_per_trade", "max_weight_per_day", "min_weight", "max_participation", "limit_up_pct"):
        if key not in cfg:
            raise ValueError(f"risk_v1.yaml 에 {key} 가 없습니다")
    return cfg


def config_hash(config_dir: Path | None = None) -> str:
    """config/*.yaml 전체의 짧은 해시. 장부의 판단 행에 남겨, 어떤 설정(숫자)으로 판단했는지 사후에 대조한다."""
    h = hashlib.sha256()
    for path in sorted((config_dir or CONFIG_DIR).glob("*.yaml")):
        h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()[:16]
