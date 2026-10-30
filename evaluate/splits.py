"""학습/검증/전진 구간 (config/splits_v1.yaml)을 평가에 적용한다 (D9: 기준값 탐색 전에 고정, 검증은 한 번만).

  train   : 기준값 탐색에 쓴다
  valid   : 한 번만 연다. 열 때마다 data/_meta/validation_runs.csv 에 남기고 2번째부터 경고한다
  forward : 모의 운영 시작일부터 (끝이 없다)
  all     : 구간을 나누지 않는다 (기준값이 없는 A0 기준선처럼 고를 값이 없는 경우)
"""
import csv
from datetime import datetime
from pathlib import Path

NAMES = ("train", "valid", "forward", "all")
LOGGED = "valid"
LOG_COLS = ["opened_at", "split", "tag"]


def window(name: str, splits: dict) -> tuple[str, str]:
    """(시작, 끝) YYYYMMDD, 양끝 포함. 끝이 없으면 99991231."""
    if name not in NAMES:
        raise ValueError(f"알 수 없는 구간: {name!r} (train/valid/forward/all)")
    if name == "all":
        return "00000101", "99991231"
    s = splits[name]
    return str(s["start"]).replace("-", ""), (str(s["end"]).replace("-", "") if s.get("end") else "99991231")


def in_split(list_date: str, name: str, splits: dict) -> bool:
    start, end = window(name, splits)
    return start <= list_date <= end


def open_split(name: str, log_path: Path, tag: str, now: datetime) -> dict:
    """구간을 연다. 검증 구간이면 기록하고, 이미 연 적이 있으면 경고 문구를 돌려준다 (막지는 않는다)."""
    if name not in NAMES:
        raise ValueError(f"알 수 없는 구간: {name!r}")
    if name != LOGGED:
        return {"opened_before": 0, "warning": ""}
    log_path = Path(log_path)
    prior = list(csv.DictReader(open(log_path, encoding="utf-8-sig"))) if log_path.exists() else []
    prior = [r for r in prior if r["split"] == LOGGED]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    new = not log_path.exists()
    with open(log_path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLS)
        if new:
            w.writeheader()
        w.writerow({"opened_at": now.isoformat(timespec="seconds"), "split": LOGGED, "tag": tag})
    warning = ""
    if prior:
        warning = (f"검증 구간을 {len(prior) + 1}번째 열었다 (이전: {prior[-1]['opened_at']} · {prior[-1]['tag']}). "
                   f"검증 구간을 반복해서 보면 사실상 학습에 쓰는 것이다 (D9)")
    return {"opened_before": len(prior), "warning": warning}
