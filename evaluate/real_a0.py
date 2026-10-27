"""실데이터 A0 백테스트: 레지스트리·공모 조건 CSV(build_dart_registry) + KRX raw → 정산 결과 CSV + 결과 문서.

  python -m evaluate.real_a0 20261026

공모가 주 출처는 DART 확정 공모가다 (KRX 역산값은 진코스텍처럼 틀릴 수 있다).
상한가 종가(공모가 ×4 근처)는 체결이 불확실하므로 '전부 체결' 값과 '상한가 제외(미체결)' 값을 같이 낸다.
코스닥 지수가 승인 전이면 기준선은 계산 불가로 표시한다.
"""
import csv
import statistics as st
import sys
from dataclasses import asdict
from datetime import date

import config
import report
from core import settings
from evaluate.backtest import run_a0
from evaluate.outcomes import BarIndex
from store.bars import calendar_bars, iter_filtered_bars
from store.facts import facts_from_registry

ROW_COLS = ["ipo_id", "short_code", "list_date", "offer_price", "entry_px", "exit_px", "gross_ret", "net_ret",
            "buy_at_limit_up", "bench_ret", "net_ret_status"]


def _rows(results):
    return [{"ipo_id": d.ipo_id, "short_code": d.short_code, "list_date": d.listing_date, "offer_price": d.offer_price,
             **{k: v for k, v in asdict(s).items() if k in ROW_COLS}} for d, s in results]


def _pct(x):
    return report.pct(x)


def _line(name, s):
    if not s:
        return f"| {name} | 0 | - | - | - | - | - | - |"
    return (f"| {name} | {s['n']} | {_pct(s['mean'])} | {_pct(s['median'])} | {s['win_rate'] * 100:.1f}% | "
            f"{_pct(s['avg_win'])} / {_pct(s['avg_loss'])} | {_pct(s['p10'])} | {_pct(s['worst'])} |")


def run(end: str, start: str | None = None) -> dict:
    start = start or config.BUFFER_START
    mart = config.MART
    facts = facts_from_registry(mart / "dart_ipo_registry.csv", mart / "dart_offer_terms.csv")
    ipo_ids = sorted({f.ipo_id for f in facts if f.var == "listing_date"})
    codes = {f.value_text for f in facts if f.var == "short_code"}
    bars = BarIndex(list(iter_filtered_bars(start, end, codes)) + calendar_bars(start, end))  # 민감도 실행까지 한 번만
    years = sorted({int(f.value_text[:4]) for f in facts if f.var == "listing_date"})
    costs = settings.load_costs(years[0], years[-1]) if years else settings.load_costs(2023, 2023)

    results = run_a0(ipo_ids, facts, bars, costs)
    rows = _rows(results)
    usable = [r for r in rows if r["net_ret"] is not None]
    ex_limit = [r for r in usable if r["buy_at_limit_up"] is not True]
    summary = report.summarize([r["net_ret"] for r in usable])
    summary_ex = report.summarize([r["net_ret"] for r in ex_limit])
    gross = report.summarize([r["gross_ret"] for r in usable])
    bench = report.summarize([r["bench_ret"] for r in usable])

    sensitivity = {}
    for slip in costs.get("slippage_sensitivity", []):
        alt = run_a0(ipo_ids, facts, bars, {**costs, "slippage_per_side": slip})
        vals = [s.net_ret for _, s in alt if s.net_ret is not None and s.buy_at_limit_up is not True]
        sensitivity[slip] = st.mean(vals) if vals else None

    mart.mkdir(parents=True, exist_ok=True)
    out_csv = mart / f"a0_real_{start}_{end}.csv"
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ROW_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r[k] is None else r[k]) for k in ROW_COLS})

    dates = sorted(r["list_date"] for r in rows if r["list_date"])
    n_unknown_limit = sum(1 for r in usable if r["buy_at_limit_up"] is None)
    n_limit = sum(1 for r in usable if r["buy_at_limit_up"] is True)
    bench_text = ("계산 불가 — 코스닥 지수 서비스(kosdaq_dd_trd) 미승인으로 수집하지 못함" if not bench
                  else f"평균 {_pct(bench['mean'])} (n={bench['n']})")
    md = f"""# A0 기준선 결과 (실데이터) — 상장일 종가 매수 → 다음 거래일 시가 매도

작성 {date.today()} · 자동 생성 초안 · 근거 D5, D7, D11, D12

## 데이터
- 대상: 코스닥 신규상장 중 DART 지분증권 신고서가 있고 KRX 종목기본정보에 상장일이 있는 종목 (레지스트리 `in_trading_universe`)
- 기간: {dates[0] if dates else '-'} ~ {dates[-1] if dates else '-'} · 대상 {len(rows)}건 · 계산 가능 {len(usable)}건 · 계산 불가 {len(rows) - len(usable)}건
- 출처: KRX Open API 코스닥 일별매매정보 (원본 `data/0_raw/krx`), DART 발행조건확정 공시 원문 (확정 공모가)
- 학습/검증 분리: 이 결과는 기준값이 없는 기준선이라 분리하지 않음

## 비용·체결 가정
- 수수료 편도 {costs['commission_per_side'] * 100:.3f}% · 슬리피지 편도 {costs['slippage_per_side'] * 100:.2f}% · 매도 거래세 연도별 {costs['kosdaq_sell_tax']}
- 하룻밤 갭은 시가 체결로 그대로 반영 (D5)
- 상한가 종가(공모가 ×4 근처) {n_limit}건은 종가 매수 체결이 불확실. 공모가를 몰라 판정할 수 없는 건 {n_unknown_limit}건
- 주 결과는 상한가 종가를 미체결로 보고 제외한 값, 전부 체결 가정은 민감도

## 성과
| 구분 | 건수 | 평균(기대값) | 중앙값 | 승률 | 평균 수익 / 평균 손실 | 하위 10% | 최대 손실 |
|---|---|---|---|---|---|---|---|
{_line('비용 차감 후 · 상한가 제외(미체결, 주 결과)', summary_ex)}
{_line('비용 차감 후 · 전부 체결 가정', summary)}
{_line('비용 차감 전 · 전부 체결 가정', gross)}

## 코스닥 기준선
- {bench_text}

## 슬리피지 민감도 (상한가 제외 평균, 비용 차감 후)
{chr(10).join(f'- 편도 {k * 100:.2f}%: {_pct(v)}' for k, v in sensitivity.items()) or '- 설정 없음'}

## 한계
- 공모가는 DART 확정 공모가 우선. KRX 역산값은 일부 종목에서 다르다(진코스텍 23,850 vs 23,500).
- 상장일·종목코드는 KRX 종목기본정보(현재 상장 종목 스냅샷)에서 와서 상장폐지된 종목이 빠진다 (생존자 편향).
- 이 결과는 필터가 없는 기준선이다. 표본이 작거나 한두 종목에 좌우되면 중앙값·하위 10%를 같이 볼 것.
"""
    out_dir = config.ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    doc = out_dir / f"{date.today()}_A0_real_v1.md"
    doc.write_text(md, encoding="utf-8")
    return {"rows": rows, "summary": summary, "summary_ex_limit_up": summary_ex, "sensitivity": sensitivity,
            "csv": str(out_csv), "doc": str(doc)}


if __name__ == "__main__":
    end_arg = sys.argv[1] if len(sys.argv) > 1 else "20261026"
    res = run(end_arg)
    print(f"[A0] {res['csv']}\n[A0] {res['doc']}\n[A0] n={res['summary']['n'] if res['summary'] else 0}")
