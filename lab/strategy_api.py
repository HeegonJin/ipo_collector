"""전략 백테스트 화면의 서버 쪽: 설계 문서 L8 요구 — 판단 코드(strategies/)를 as_of 만 바꿔 과거로 돌린다 (별도 계산 금지).

lab/engine.py 의 조건 필터가 '상장일 값'으로 빠르게 훑는 탐색 도구라면, 여기는 팀이 고정한 전략 규칙(config/strategy_*_v1.yaml)을
PitReader 로 날짜마다 판단해 진입하고, 청산 규칙대로 모의 체결한다 (모의 운영과 같은 코드).
규칙 숫자를 바꿔 볼 수 있지만 '탐색'으로 표시하고 시도 횟수에 더하며, 학습 구간에서만 돌린다 (검증 구간은 랩 탭의 잠금으로만).
"""
import copy
import hashlib
import json
import statistics as st
from datetime import date, datetime

import yaml

import config
from core import settings
from core.pit import PitReader
from core.tradingcal import KST
from evaluate import splits as splitlib
from evaluate import swing
from evaluate.backtest import run_a0
from evaluate.outcomes import BarIndex
from lab import engine, guards
from store.bars import INDEX_CODE
from strategies import a0, b, c

# 바꿔 볼 수 있는 규칙 숫자 (dotted 경로: 라벨, 최소, 최대, 간격, 정수 여부). 범위 밖은 거절한다.
KNOBS = {
    "B_v1": {
        "entry.max_demand_ratio": ("기관 경쟁률 상한 (이하 = 흥행 실패)", 50, 1500, 50, False),
        "entry.max_close_vs_offer": ("종가 ≤ 공모가 × 이 값", 0.5, 1.5, 0.05, False),
        "entry.market_rebound_pct": ("코스닥 저점 대비 반등 (%)", 0, 30, 1, False),
        "entry.market_lookback_days": ("코스닥 저점 탐색 기간 (거래일)", 20, 120, 10, True),
        "entry.min_days_since_listing": ("상장 후 최소 거래일", 5, 60, 5, True),
        "entry.max_days_since_listing": ("상장 후 최대 거래일", 60, 120, 10, True),
        "exit.hold_days": ("보유 거래일", 5, 120, 5, True),
        "exit.stop_loss_pct": ("손절 (%)", 3, 40, 1, False),
        "exit.take_profit_pct": ("익절 (%)", 5, 100, 5, False),
    },
    "C_v1": {
        "entry.min_unlock_pct": ("해제 확약 수량 ÷ 상장 주식수 하한 (%)", 1, 30, 1, False),
        "entry.volume_spike_x": ("거래량 급증 배수", 1.5, 10, 0.5, False),
        "entry.window_days": ("해제일 후 관찰 거래일", 3, 10, 1, True),
        "entry.stable_range_pct": ("가격 안정 폭 (%)", 2, 15, 1, False),
        "entry.min_close_vs_pre_unlock": ("해제 전날 종가 대비 최소 비율", 0.5, 1.0, 0.05, False),
        "exit.hold_days": ("보유 거래일", 5, 120, 5, True),
        "exit.stop_loss_pct": ("손절 (%)", 3, 40, 1, False),
        "exit.take_profit_pct": ("익절 (%)", 5, 100, 5, False),
    },
}
LABELS = {"A0": "A0 기준선 — 상장일 종가 매수 → 다음 거래일 시가 매도",
          "B_v1": "B 흥행 실패주 반등 (v1)", "C_v1": "C 매물 소화 후 회복 (v1)"}
MODULES = {"B_v1": b, "C_v1": c}
CONCENTRATION_TOP = 2


def _get(d: dict, path: str):
    for k in path.split("."):
        d = d[k]
    return d


def _set(d: dict, path: str, value) -> None:
    *head, last = path.split(".")
    for k in head:
        d = d[k]
    d[last] = value


def apply_overrides(strategy: str, base: dict, overrides: dict) -> dict:
    """규칙 파일 숫자에 덮어쓸 값을 검증해 적용한 사본. 모르는 항목·범위 밖·정수 아님은 ValueError."""
    knobs, params = KNOBS.get(strategy, {}), copy.deepcopy(base)
    for path, v in (overrides or {}).items():
        if path not in knobs:
            raise ValueError(f"바꿀 수 없는 항목: {path!r}")
        _, lo, hi, _, is_int = knobs[path]
        v = float(v)
        if not lo <= v <= hi:
            raise ValueError(f"{path}: 범위 밖 ({lo}~{hi})")
        if is_int:
            if v != int(v):
                raise ValueError(f"{path}: 정수여야 함")
            v = int(v)
        _set(params, path, v)
    if strategy == "B_v1" and params["entry"]["min_days_since_listing"] > params["entry"]["max_days_since_listing"]:
        raise ValueError("상장 후 최소 거래일이 최대보다 큽니다")
    return params


def changed(strategy: str, base: dict, params: dict) -> dict:
    return {p: _get(params, p) for p in KNOBS.get(strategy, {}) if _get(params, p) != _get(base, p)}


def concentration(rets: list[float]) -> dict:
    """한두 종목 집중 점검 (설계 L8 견고성): 평균이 양수인데 상위 2건을 빼면 0 이하이면 '쏠림 의심'."""
    if len(rets) <= CONCENTRATION_TOP:
        return {"verdict": "판단 불가", "mean_without_top": None}
    rest = sorted(rets, reverse=True)[CONCENTRATION_TOP:]
    m_all, m_rest = st.mean(rets), st.mean(rest)
    return {"verdict": "쏠림 의심" if m_all > 0 and m_rest <= 0 else "분산", "mean_without_top": m_rest}


class StrategyLab:
    def __init__(self, universe: list[dict], facts: list, index: BarIndex, costs: dict, splits: dict, trials: guards.TrialLog,
                 cfg: dict, start: str, end: str):
        self.universe, self.facts, self.index, self.costs, self.splits = universe, facts, index, costs, splits
        self.trials, self.cfg, self.start, self.end = trials, cfg, start, end
        self._cache: dict[str, list[dict]] = {}

    # ── 목록 ──
    def catalog(self) -> dict:
        out = []
        for sid, label in LABELS.items():
            base = settings.load_strategy(sid) if sid in KNOBS else None
            knobs = [{"path": p, "label": k[0], "min": k[1], "max": k[2], "step": k[3], "default": _get(base, p)}
                     for p, k in KNOBS.get(sid, {}).items()]
            out.append({"id": sid, "label": label, "knobs": knobs,
                        "yaml": yaml.safe_dump({k: base[k] for k in ("entry", "exit")}, allow_unicode=True, sort_keys=False) if base else None})
        return {"strategies": out, "split": "train", "min_n": self.cfg["min_n"]}

    def ipos(self) -> list[dict]:
        return [{"ipo_id": r["ipo_id"], "name": r["corp_name"], "list_date": r["list_dd"],
                 "split": next((s for s in ("train", "valid", "forward") if splitlib.in_split(r["list_dd"], s, self.splits)), "none")}
                for r in sorted(self.universe, key=lambda r: r["list_dd"])]

    # ── 백테스트 ──
    def _train_universe(self) -> list[dict]:
        return [r for r in self.universe if splitlib.in_split(r["list_dd"], "train", self.splits)]

    def _trades(self, strategy: str, params: dict) -> list[dict]:
        key = strategy + hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:10]
        if key not in self._cache:
            if strategy == "A0":
                self._cache[key] = self._a0_trades()
            else:
                self._cache[key] = [t for r in self._train_universe() for t in swing.scan_ipo(
                    strategy, params, r["ipo_id"], r["corp_name"], self.facts, self.index, r["stock_code"], r["list_dd"], self.costs)]
        return self._cache[key]

    def _a0_trades(self) -> list[dict]:
        ids = [r["ipo_id"] for r in self._train_universe()]
        names = {r["ipo_id"]: r["corp_name"] for r in self.universe}
        out = []
        for d, s in run_a0(ids, self.facts, self.index, self.costs):
            out.append({"ipo_id": d.ipo_id, "name": names.get(d.ipo_id, d.ipo_id), "signal_date": d.listing_date, "entry_date": d.listing_date,
                        "entry_px": s.entry_px, "exit_date": None, "reason": "D1 시가", "kind": s.exit_kind, "net_ret": s.net_ret,
                        "gross_ret": s.gross_ret, "bench_ret": s.bench_ret, "no_fill": False, "limit_up": s.buy_at_limit_up})
        return out

    def run(self, strategy: str, overrides: dict | None = None) -> dict:
        if strategy not in LABELS:
            raise ValueError(f"알 수 없는 전략: {strategy!r}")
        base = settings.load_strategy(strategy) if strategy in KNOBS else {}
        params = apply_overrides(strategy, base, overrides or {}) if base else base
        diff = changed(strategy, base, params) if base else {}
        if diff:                                      # 규칙을 바꾼 시도는 랩과 같은 다중비교 카운터에 더한다
            self.trials.record({"strategy": strategy, "overrides": diff})
        trades = self._trades(strategy, params)
        done = [t for t in trades if not t.get("no_fill") and t.get("net_ret") is not None and not t.get("limit_up")]
        a0_done = [t for t in self._trades("A0", {}) if t.get("net_ret") is not None and not t.get("limit_up")]
        rets = [t["net_ret"] for t in done]
        excess = [t["net_ret"] - t["bench_ret"] for t in done if t.get("bench_ret") is not None]
        n = self.cfg["min_n"]
        stats, d = engine.summarize(rets), self.trials.distinct()
        return {
            "strategy": strategy, "label": LABELS[strategy], "split": "train", "version": params.get("version", "A0_v1"),
            "overrides": diff, "exploratory": bool(diff),
            "signals": len(trades), "no_fill": sum(1 for t in trades if t.get("no_fill")),
            "pending": sum(1 for t in trades if not t.get("no_fill") and t.get("net_ret") is None),
            "limit_up_excluded": sum(1 for t in trades if t.get("limit_up")),
            "stats": guards.mask(stats, n), "baseline_a0": guards.mask(engine.summarize([t["net_ret"] for t in a0_done]), n),
            "excess_vs_kosdaq": guards.mask(engine.summarize(excess), n),
            "concentration": concentration(rets) if len(rets) >= n else {"verdict": "판단 불가", "mean_without_top": None},
            "by_reason": {k: guards.mask(engine.summarize([t["net_ret"] for t in done if t.get("reason") == k]), n)
                          for k in sorted({t.get("reason") for t in done if t.get("reason")})},
            "exit_kinds": {k: sum(1 for t in done if t.get("kind") == k) for k in ("정상", "거래정지", "폐지")},
            "trials": {"distinct": d, "chance_best": guards.chance_best(d, stats.get("se")), "warn": d >= self.cfg["trials_warn_at"],
                       "warn_at": self.cfg["trials_warn_at"]},
            "trades": [] if stats.get("n", 0) < n else [
                {k: t.get(k) for k in ("name", "signal_date", "entry_date", "exit_date", "reason", "kind", "net_ret", "bench_ret")} for t in done],
            "costs": {"commission_per_side": self.costs["commission_per_side"], "slippage_per_side": self.costs["slippage_per_side"],
                      "kosdaq_sell_tax": {str(k): v for k, v in self.costs["kosdaq_sell_tax"].items()}},
            "doc": self.result_doc(strategy, params, trades, diff),
        }

    def result_doc(self, strategy: str, params: dict, trades: list[dict], diff: dict) -> str:
        """results/README 형식의 결과 문서 (데이터 기간·비용·체결 가정·평균/중앙값/승률/손익비/최악·기준선)."""
        if strategy == "A0":
            done = [t for t in trades if t.get("net_ret") is not None and not t.get("limit_up")]
            L = [swing._line("A0 (상한가 종가 제외)", [t["net_ret"] for t in done])]
            return "\n".join([
                f"# A0 기준선 백테스트 (학습 구간, 앱에서 생성)", "", f"작성 {date.today()} · 시세 {self.start} ~ {self.end} (KRX statistical information)",
                "", "| 구분 | 건수 | 평균(기대값) | 중앙값 | 승률 | 평균 수익 / 평균 손실 | 하위 10% | 최대 손실 |", "|---|---|---|---|---|---|---|---|", *L,
                "", "상장일 종가 매수 → 다음 거래일 시가 매도, 비용·연도별 매도세 차감, 상한가 종가는 체결 불확실이라 제외."]) + "\n"
        text = swing.render(strategy, params, trades, len(self._train_universe()), "train", self.splits, self.start, self.end, self.costs)
        if diff:
            text += ("\n## 탐색 표시\n- 이 결과는 규칙 파일 값을 앱에서 바꿔 본 **탐색**입니다: "
                     + ", ".join(f"{k}={v}" for k, v in diff.items()) + "\n- 다중비교 때문에 좋아 보이는 값은 우연일 수 있다. 채택하려면 새 버전 config 로 고정하고 forward 에서 확인한다 (D9).\n")
        return text

    # ── PIT 카드 ──
    def pit_card(self, ipo_id: str, as_of_iso: str) -> dict:
        row = next((r for r in self.universe if r["ipo_id"] == ipo_id), None)
        if row is None:
            raise ValueError(f"알 수 없는 종목: {ipo_id!r}")
        as_of = datetime.fromisoformat(as_of_iso)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=KST)
        mine = [f for f in self.facts if f.ipo_id == ipo_id]
        view = lambda f: {"var": f.var, "value": f.value_num if f.value_num is not None else f.value_text, "status": f.status.value,
                          "available_at": f.available_at.isoformat(), "source_id": f.source_id, "phase": f.information_phase.value}  # noqa: E731
        visible = sorted((view(f) for f in mine if f.available_at <= as_of), key=lambda x: x["available_at"])
        hidden = sorted((view(f) for f in mine if f.available_at > as_of), key=lambda x: x["available_at"])
        bars = [bar for d in self.index.code(row["stock_code"]).values() for bar in (d,)]
        bars += list(self.index.code(INDEX_CODE).values())
        reader = PitReader(mine, bars, as_of)
        signals = []
        sig = a0.evaluate(reader, ipo_id)
        signals.append({"strategy": "A0", "action": sig.action, "reasons": list(sig.reasons)})
        for sid, mod in MODULES.items():
            s = mod.evaluate(reader, ipo_id, settings.load_strategy(sid))
            signals.append({"strategy": sid, "action": s.action, "reasons": list(s.reasons)})
        return {"ipo_id": ipo_id, "name": row["corp_name"], "as_of": as_of.isoformat(), "list_date": row["list_dd"],
                "visible": visible, "hidden": hidden, "signals": signals,
                "bars_visible": len(reader.bars(row["stock_code"])),
                "note": "as_of 이후에 공개되는 값(hidden)은 판단 코드가 읽지 못한다 — PitReader 가 걸러낸다 (백테스트·모의 운영 공통)."}
