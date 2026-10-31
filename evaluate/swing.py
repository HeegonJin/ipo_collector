"""전략 B·C(며칠~몇 주 보유) 평가: 신호 → 다음 거래일 시가 매수 → 기간·손절·익절 청산을 일봉으로 모의한다.

미래 가격을 읽는 곳이라 evaluate 에 있다. 신호는 판단 계층(strategies/)이 PitReader 로만 읽어 낸다.
같은 코드로 백테스트와 모의 운영 정산(settle_swing)을 한다.

청산 규칙 (config/strategy_*_v1.yaml 의 exit)
  - 매수일 포함 N번째 거래일(hold_days) 시가에 매도
  - 그 전에 종가가 매수가 대비 -stop_loss_pct 이하 또는 +take_profit_pct 이상이면 다음 거래일 시가에 매도 (종가를 보고 다음 날 시가에 체결)
  - 청산일에 거래정지면 재개 후 첫 시가, 그 뒤로 거래가 없으면(폐지) 마지막 종가, 청산일이 아직 오지 않았으면 미도래

  python -m evaluate.swing B_v1 20261029          # 학습 구간 백테스트 → results/*_B_v1_train.md
"""
import bisect
import csv
import statistics as st
from datetime import date, datetime, timedelta

import yaml

import config
from core import settings
from core.pit import PitReader
from core.tradingcal import KST, krx_daily_available_at
from decide.runner import Decision
from evaluate import splits as splitlib
from evaluate.outcomes import BarIndex, Settlement, _net
from report import summarize
from store.bars import INDEX_CODE, calendar_bars, iter_filtered_bars, iter_index_bars
from store.facts import facts_from_demand_mart, facts_from_registry
from strategies import b, c

STRATEGIES = {"B_v1": (b, 121), "C_v1": (c, 140)}   # (모듈, 상장 후 몇 거래일까지 훑을지)
DECISION_DELAY = timedelta(minutes=30)               # 일봉이 공개되는 08:00 뒤, 개장 전에 판단


def as_of_for(signal_date: str) -> datetime:
    """signal_date 일봉까지 보고 판단하는 시각 = 그 다음 거래일 08:30."""
    d = datetime.strptime(signal_date, "%Y%m%d").date()
    return krx_daily_available_at(d) + DECISION_DELAY


def _rates(costs: dict, exit_date: str) -> tuple:
    tax = costs["kosdaq_sell_tax"]
    year = int(exit_date[:4])
    if year not in tax:
        raise ValueError(f"매도세율이 없는 연도: {year}")
    return costs["commission_per_side"], costs["slippage_per_side"], tax[year]


def simulate_exit(mine: dict, cal: list[str], entry_date: str, entry_px: float, exit_cfg: dict) -> dict:
    """mine: {날짜: bar}, cal: 정렬된 거래일 달력. 반환: exit_date, exit_px, reason, kind(정상|거래정지|폐지|미도래)."""
    i0 = bisect.bisect_left(cal, entry_date)
    hold, sl, tp = exit_cfg["hold_days"], exit_cfg["stop_loss_pct"], exit_cfg["take_profit_pct"]

    def open_from(j: int, reason: str):
        """달력 j 번째 거래일 시가 (정지면 이후 첫 시가). 달력 밖이면 미도래, 이후 거래가 없으면 폐지."""
        if j >= len(cal):
            return {"exit_date": None, "exit_px": None, "reason": reason, "kind": "미도래"}
        for jj in range(j, len(cal)):
            bar = mine.get(cal[jj])
            if bar and bar.get("open"):
                return {"exit_date": cal[jj], "exit_px": bar["open"], "reason": reason, "kind": "정상" if jj == j else "거래정지"}
        last = max((d for d in mine if d < cal[j]), default=None)
        return {"exit_date": last, "exit_px": mine[last]["close"] if last else None, "reason": reason, "kind": "폐지"}

    for k in range(hold):
        j = i0 + k
        if j >= len(cal):
            return open_from(j, "기간")
        bar = mine.get(cal[j])
        close = bar.get("close") if bar else None
        if close is None:
            continue
        if close <= entry_px * (1 - sl / 100):
            return open_from(j + 1, "손절")
        if close >= entry_px * (1 + tp / 100):
            return open_from(j + 1, "익절")
    return open_from(i0 + hold, "기간")


def _result(entry_px: float, ex: dict, costs: dict, bench: float | None) -> dict:
    gross = net = None
    if ex["exit_px"] is not None and ex["exit_date"] is not None:
        gross = ex["exit_px"] / entry_px - 1
        net = _net(ex["exit_px"], entry_px, _rates(costs, ex["exit_date"]))
    return {**ex, "gross_ret": gross, "net_ret": net, "bench_ret": bench}


def _bench(idx: dict, entry_date: str, exit_date: str | None):
    a, z = idx.get(entry_date), idx.get(exit_date) if exit_date else None
    return z["open"] / a["open"] - 1 if a and z and a.get("open") and z.get("open") else None


def settle_swing(decision: Decision, index: BarIndex, costs: dict) -> Settlement:
    """모의 운영 정산. 매수일 = 판단일(as_of) 이후 첫 거래일, 규칙은 decision.exit_rule 이 가리키는 config 버전."""
    if decision.action != "매수":
        raise ValueError("매수 결정만 정산한다")
    cfg = settings.load_strategy(decision.exit_rule)
    mine = index.code(decision.short_code)
    day = decision.as_of.astimezone(KST).strftime("%Y%m%d")
    entry_date = next((d for d in index.calendar if d >= day and d in mine), None)
    if entry_date is None or not mine[entry_date].get("open"):
        return Settlement(decision.ipo_id, decision.strategy, None, None, None, None, None, None, "계산 불가", "미도래")
    entry_px = mine[entry_date]["open"]
    ex = simulate_exit(mine, index.calendar, entry_date, entry_px, cfg["exit"])
    r = _result(entry_px, ex, costs, _bench(index.code(INDEX_CODE), entry_date, ex["exit_date"]))
    return Settlement(decision.ipo_id, decision.strategy, entry_px, r["exit_px"], r["gross_ret"], r["net_ret"], None, r["bench_ret"],
                      "확인" if r["net_ret"] is not None else "계산 불가", r["kind"], exit_date=r["exit_date"], exit_reason=r["reason"])


# ── 백테스트 ───────────────────────────────────────────────────
def scan_ipo(strategy: str, params: dict, ipo_id: str, name: str, facts: list, index: BarIndex, code: str, listing: str,
             costs: dict) -> list[dict]:
    module, scan_days = STRATEGIES[strategy]
    mine = index.code(code)
    dates = sorted(d for d in mine if d >= listing)
    idx_bars = sorted(index.code(INDEX_CODE).values(), key=lambda x: x["date"])
    idx_dates = [x["date"] for x in idx_bars]
    own_bars = [mine[d] for d in dates]
    own_facts = [f for f in facts if f.ipo_id == ipo_id]
    trades, free_after = [], ""
    for n, t in enumerate(dates[:scan_days]):
        if t <= free_after:
            continue
        reader = PitReader(own_facts, own_bars[:n + 1] + idx_bars[:bisect.bisect_right(idx_dates, t)], as_of_for(t))
        sig = module.evaluate(reader, ipo_id, params)
        if sig.action != "매수":
            continue
        entry_date = next((d for d in index.calendar if d > t), None)
        bar = mine.get(entry_date) if entry_date else None
        if not bar or not bar.get("open"):
            trades.append({"ipo_id": ipo_id, "name": name, "signal_date": t, "entry_date": entry_date, "no_fill": True,
                           "reasons": list(sig.reasons)})
            continue
        ex = simulate_exit(mine, index.calendar, entry_date, bar["open"], params["exit"])
        r = _result(bar["open"], ex, costs, _bench(index.code(INDEX_CODE), entry_date, ex["exit_date"]))
        trades.append({"ipo_id": ipo_id, "name": name, "signal_date": t, "entry_date": entry_date, "entry_px": bar["open"],
                       "reasons": list(sig.reasons), "no_fill": False, **r})
        free_after = ex["exit_date"] or "99999999"        # 포지션을 들고 있는 동안은 같은 종목의 새 신호를 보지 않는다
        if module is b:                                    # B 는 종목당 한 번
            break
    return trades


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def run(strategy: str, end: str, split: str = "train", start: str | None = None, splits: dict | None = None,
        out_dir=None) -> dict:
    if split == "valid":
        raise ValueError("검증 구간은 이 명령으로 열지 않는다 (valid 는 한 번만 연다)")
    start = start or config.BUFFER_START
    splits = splits or settings.load_splits()
    params = settings.load_strategy(strategy)
    mart = config.MART
    universe = [r for r in _read(mart / "dart_ipo_registry.csv") if r["in_trading_universe"] == "True" and r["list_dd"]]
    universe = [r for r in universe if splitlib.in_split(r["list_dd"], split, splits)]
    facts = facts_from_registry(mart / "dart_ipo_registry.csv", mart / "dart_offer_terms.csv") + \
        facts_from_demand_mart(mart / "dart_demand.csv")
    codes = {r["stock_code"] for r in universe}
    index = BarIndex(list(iter_filtered_bars(start, end, codes)) + calendar_bars(start, end) + list(iter_index_bars(start, end)))
    first_year = min((int(r["list_dd"][:4]) for r in universe), default=2023)
    costs = settings.load_costs(first_year, int(end[:4]))        # 청산은 상장 뒤에 일어나므로 데이터 마지막 연도까지 세율이 필요하다
    trades = []
    for r in universe:
        trades += scan_ipo(strategy, params, r["ipo_id"], r["corp_name"], facts, index, r["stock_code"], r["list_dd"], costs)
    out_dir = out_dir or config.ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    doc = out_dir / f"{date.today()}_{strategy}_{split}.md"
    doc.write_text(render(strategy, params, trades, len(universe), split, splits, start, end, costs), encoding="utf-8")
    return {"trades": trades, "doc": str(doc), "universe": len(universe)}


def _line(label: str, vals: list[float]) -> str:
    s = summarize(vals)
    if not s:
        return f"| {label} | 0 | - | - | - | - | - | - |"
    return (f"| {label} | {s['n']} | {s['mean'] * 100:+.2f}% | {s['median'] * 100:+.2f}% | {s['win_rate'] * 100:.1f}% | "
            f"{s['avg_win'] * 100:+.2f}% / {s['avg_loss'] * 100:+.2f}% | {s['p10'] * 100:+.2f}% | {s['worst'] * 100:+.2f}% |")


def render(strategy, params, trades, n_universe, split, splits, start, end, costs) -> str:
    done = [t for t in trades if not t.get("no_fill") and t.get("net_ret") is not None]
    pending = [t for t in trades if not t.get("no_fill") and t.get("net_ret") is None]
    nofill = [t for t in trades if t.get("no_fill")]
    s, e = splitlib.window(split, splits)
    by_reason = {k: [t["net_ret"] for t in done if t["reason"] == k] for k in ("기간", "손절", "익절")}
    bench = [t["bench_ret"] for t in done if t.get("bench_ret") is not None]
    excess = [t["net_ret"] - t["bench_ret"] for t in done if t.get("bench_ret") is not None]
    kinds = {k: sum(1 for t in done if t["kind"] == k) for k in ("정상", "거래정지", "폐지")}
    note = ("- 전략 C 의 해제일은 상장일 + 확약 기간으로 추정했고, '실제 매도 확인'은 거래량 급증으로 대신했다 (예탁결제원 해제 일정·투자자별 매매 미수집)."
            if strategy.startswith("C") else "- 전략 B 는 섹터 지수 조건 없이 코스닥 지수만 쓴다 (섹터 데이터 미수집).")
    L = [f"# 전략 {strategy} 백테스트 (실데이터, {split} 구간)", "",
         f"작성 {date.today()} · 자동 생성 초안 · 규칙 파일 `config/strategy_{strategy}.yaml` (사람이 고정, D9) · 규칙 숫자는 문서에 없어 PM 대행(Claude)이 제안한 값", "",
         "## 데이터",
         f"- 대상: 레지스트리 매매 대상 중 {split} ({s}~{'계속' if e == '99991231' else e}, 상장일 기준) {n_universe}종목",
         f"- 시세 {start} ~ {end}, KRX Open API 코스닥 일별매매정보·KOSDAQ 시리즈, DART 공시(경쟁률·확약 수량)",
         "- 이 문서는 **KRX statistical information** (한국거래소 통계정보)을 이용해 만들었다 (KRX OPEN API 약관 Art.10(3)). "
         "원천 데이터는 비상업 목적으로만 쓰며 제3자에게 제공하지 않는다 (Art.6(2), Art.11(2)).",
         f"- 학습/검증 분리: {split} 만 사용했다. 검증 구간은 열지 않았다.", "",
         "## 규칙 (요약)", "```yaml",
         yaml.safe_dump({k: params[k] for k in ("entry", "exit")}, allow_unicode=True, sort_keys=False).rstrip(), "```", "",
         "## 비용·체결 가정",
         f"- 수수료 편도 {costs['commission_per_side'] * 100:.3f}% · 슬리피지 편도 {costs['slippage_per_side'] * 100:.2f}% · 매도세는 청산 연도 기준 {costs['kosdaq_sell_tax']}",
         "- 신호는 일봉이 공개된 다음 거래일 08:30 에 판단하고 그날 시가에 산다. 손절·익절은 종가를 보고 다음 거래일 시가에 판다 (장중 터치는 보지 않음).",
         "- 시가 체결은 호가가 얇으면 불리할 수 있다. 상한가 시가 등 체결 불확실성은 반영하지 않았다.", "",
         "## 성과 (비용 차감 후)",
         f"- 신호 {len(trades)}건 → 체결 {len(done) + len(pending)}건 (매수일 시세 없음 {len(nofill)}건), 청산 완료 {len(done)}건, 미도래·계산 불가 {len(pending)}건",
         f"- 청산 종류: 정상 {kinds['정상']} · 거래정지 {kinds['거래정지']} · 폐지 {kinds['폐지']} (폐지는 마지막 종가로 청산했다고 가정)", "",
         "| 구분 | 건수 | 평균(기대값) | 중앙값 | 승률 | 평균 수익 / 평균 손실 | 하위 10% | 최대 손실 |", "|---|---|---|---|---|---|---|---|",
         _line("전체", [t["net_ret"] for t in done])] + [_line(f"청산 사유: {k}", v) for k, v in by_reason.items()]
    L += ["", "## 코스닥 기준선"]
    if excess:
        L += [f"- 같은 기간(매수일 시가 → 청산일 시가) 코스닥 지수 수익률 평균 {st.mean(bench) * 100:+.2f}% (n={len(bench)})",
              f"- 종목별 초과수익(순수익 − 기준선) 평균 {st.mean(excess) * 100:+.2f}%, 중앙값 {st.median(excess) * 100:+.2f}% (n={len(excess)})",
              "- D12 판정 기준(기대값 > 0 + 지수 대비 우위)은 첫 실험용이다. 여기서는 참고로만 본다."]
    else:
        L += ["- 계산 불가 (청산 완료 건이 없거나 지수 자료 없음)"]
    L += ["", "## 읽을 때 주의",
          f"- 청산 완료 {len(done)}건이다. 한 조건에 10건 미만이면 결론을 내지 않는다 (설계 문서). 통계적 유의성은 검정하지 않았다.",
          "- 규칙 숫자는 결과를 보기 전에 고정한 제안값이다. 이 결과를 보고 숫자를 고치면 새 버전 파일로 만들고, 그때부터는 학습 구간에서 탐색한 것이 된다.",
          note]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="전략 B·C 백테스트")
    ap.add_argument("strategy", choices=sorted(STRATEGIES))
    ap.add_argument("end", nargs="?", default="20261026")
    ap.add_argument("--split", default="train", choices=("train", "forward", "all"))
    a = ap.parse_args()
    res = run(a.strategy, a.end, a.split)
    print(f"[{a.strategy}] 대상 {res['universe']}종목, 신호 {len(res['trades'])}건  {res['doc']}")
