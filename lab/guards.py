"""전략 실험 앱의 과적합 방지 장치 4가지. 조건을 사람이 계속 바꿔 보는 앱은 그냥 두면 우연히 좋아 보이는 조합을 찾는 기계가 된다.

  1. 최소 표본 수      : 거래가 min_n 보다 적으면 수익률 숫자를 아예 보여주지 않는다
  2. 시도 횟수 카운터  : 서로 다른 조건 조합을 몇 개 봤는지 기록하고, 우연만으로 기대되는 최고 평균을 보여준다
  3. 이웃 구간 견고성  : 기준값을 한 칸씩 옮긴 변형도 비슷한 결과인지 본다 (한 점만 좋으면 의심)
  4. 검증 구간 잠금    : 확인 문구를 입력하고, 학습 구간에서 먼저 평가한 조건만, 열 때마다 기록하며 2번째부터 경고 (D9)
기준값은 config/lab_v1.yaml (사람이 고정, 바꾸려면 새 버전).
"""
import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from core import settings
from evaluate import splits as splitlib
from lab import engine


def load_lab_config() -> dict:
    return settings.load_lab()


# ── 1. 최소 표본 수 ──────────────────────────────────────────────
def mask(stats: dict, min_n: int) -> dict:
    n = stats.get("n", 0)
    if n < min_n:
        return {"n": n, "insufficient": True, "min_n": min_n}      # 숫자를 주지 않는다: 작은 표본의 평균은 보지 않는 편이 낫다
    return {**stats, "insufficient": False}


# ── 2. 시도 횟수 카운터 ──────────────────────────────────────────
def params_hash(eff: dict) -> str:
    """정규형(켜진 조건만, 키 순서 고정) 해시. 꺼진 조건이나 키 순서는 같은 시도로 센다."""
    return hashlib.sha1(json.dumps(eff, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:10]


class TrialLog:
    COLS = ["ts", "hash", "params"]

    def __init__(self, path: Path):
        self.path = Path(path)

    def _rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return list(csv.DictReader(open(self.path, encoding="utf-8-sig")))

    def record(self, eff: dict) -> str:
        h = params_hash(eff)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        with open(self.path, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.COLS)
            if new:
                w.writeheader()
            w.writerow({"ts": datetime.now().isoformat(timespec="seconds"), "hash": h,
                        "params": json.dumps(eff, ensure_ascii=False)})
        return h

    def items(self) -> list[dict]:
        """기록 순서대로 (같은 조합이 여러 번이면 여러 줄)."""
        return [{"ts": r["ts"], "hash": r["hash"], "params": json.loads(r["params"])} for r in self._rows()]

    def seen(self, h: str) -> bool:
        return any(r["hash"] == h for r in self._rows())

    def distinct(self) -> int:
        return len({r["hash"] for r in self._rows()})

    def total(self) -> int:
        return len(self._rows())


def chance_best(n_trials: int, se: float | None) -> float:
    """평균이 0 인 조합을 n_trials 개 보았을 때 그중 최고가 우연만으로 기대되는 평균(근사): se·√(2 ln N).
    se 는 평균의 표준오차. 시도가 많을수록 '좋아 보이는' 값은 쉽게 나온다."""
    if not se or n_trials < 2:
        return 0.0
    return se * math.sqrt(2 * math.log(n_trials))


# ── 3. 이웃 구간 견고성 ──────────────────────────────────────────
def _to_params(eff: dict) -> dict:
    return {"entry": eff["entry"], "hold": eff["hold"],
            "conditions": {cid: {"enabled": True, "lo": lo, "hi": hi} for cid, (lo, hi) in eff["conditions"].items()}}


def _neighbors(eff: dict):
    """기준값 한 칸(step)씩 옮긴 변형과 인접 보유기간. 범위를 벗어나거나 하한이 상한을 넘는 변형은 만들지 않는다."""
    for cid, (lo, hi) in eff["conditions"].items():
        meta = engine.BY_ID[cid]
        s = meta["step"]
        for label, new_lo, new_hi in ((f"{meta['label']} 하한 −{s:g}", lo - s, hi), (f"{meta['label']} 하한 +{s:g}", lo + s, hi),
                                      (f"{meta['label']} 상한 −{s:g}", lo, hi - s), (f"{meta['label']} 상한 +{s:g}", lo, hi + s)):
            if new_lo > new_hi or new_lo < meta["min"] or new_hi > meta["max"]:
                continue
            variant = {**eff, "conditions": {**eff["conditions"], cid: [new_lo, new_hi]}}
            yield label, variant
    i = engine.HOLDS.index(eff["hold"])
    for j in (i - 1, i + 1):
        if 0 <= j < len(engine.HOLDS):
            yield f"보유기간 {engine.HOLDS[j]}일", {**eff, "hold": engine.HOLDS[j]}


def robustness(rows: list[dict], params: dict, costs: dict, split: str, min_n: int) -> dict:
    eff = engine.normalize(params)
    center = engine.evaluate(rows, _to_params(eff), costs, split)["stats"]
    out = []
    for label, variant in _neighbors(eff):
        stats = engine.evaluate(rows, _to_params(variant), costs, split)["stats"]
        ok = stats.get("n", 0) >= min_n
        out.append({"label": label, "n": stats.get("n", 0), "mean": stats["mean"] if ok else None})
    valid = [n["mean"] for n in out if n["mean"] is not None]
    if center.get("n", 0) < min_n or not valid:
        return {"verdict": "판단 불가", "neighbors": out, "flip_share": None}
    c = center["mean"]
    flip = sum(1 for m in valid if m * c < 0) / len(valid)
    spiky = c > max(valid) and (c - max(valid)) > (center.get("se") or 0)      # 중심만 이웃보다 한 표준오차 넘게 튄다
    return {"verdict": "취약" if flip > 0.25 or spiky else "견고", "neighbors": out, "flip_share": flip}


# ── 4. 검증 구간 잠금 ────────────────────────────────────────────
class ValidationGate:
    def __init__(self, rows: list[dict], costs: dict, trials: TrialLog, log_path: Path, cfg: dict):
        self.rows, self.costs, self.trials, self.log_path, self.cfg = rows, costs, trials, Path(log_path), cfg

    def open(self, params: dict, confirm: str, now: datetime) -> dict:
        if confirm != self.cfg["confirm_phrase"]:
            raise PermissionError("확인 문구가 다릅니다 — 검증 구간은 한 번만 열어야 하므로 문구를 그대로 입력해야 합니다")
        eff = engine.normalize(params)
        h = params_hash(eff)
        if not self.trials.seen(h):
            raise PermissionError("학습 구간에서 먼저 평가한 조건만 검증 구간에서 열 수 있습니다")
        opened = splitlib.open_split("valid", self.log_path, f"lab {h}", now)
        res = engine.evaluate(self.rows, params, self.costs, "valid")
        n = self.cfg["min_n"]
        return {"split": "valid", "hash": h, "stats": mask(res["stats"], n), "baseline": mask(res["baseline"], n),
                "excluded": res["excluded"], "lookahead": res["lookahead"], "warning": opened["warning"]}
