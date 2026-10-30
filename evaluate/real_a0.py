"""실데이터 A0 백테스트: 레지스트리·공모 조건 CSV(build_dart_registry) + KRX raw → 정산 결과 CSV + 결과 문서.

  python -m evaluate.real_a0 20261026

공모가 주 출처는 DART 확정 공모가다 (KRX 역산값은 진코스텍처럼 틀릴 수 있다).
상한가 종가(공모가 ×4)는 체결이 불확실하다. 주 결과는 '상한가가 아님이 확인된 건'만 쓰고,
공모가를 몰라 판정할 수 없는 건은 따로 보고하며, '전부 체결' 값은 민감도로 함께 낸다.
코스닥 지수가 승인 전이면 기준선은 계산 불가로 표시한다.
"""
import collections
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
from store.bars import calendar_bars, iter_filtered_bars, iter_index_bars
from store.facts import facts_from_registry

ROW_COLS = ["ipo_id", "short_code", "list_date", "offer_price", "entry_px", "exit_px", "gross_ret", "net_ret",
            "buy_at_limit_up", "bench_ret", "net_ret_status", "exit_kind", "net_ret_last_close", "net_ret_wipeout"]


def _rows(results):
    return [{"ipo_id": d.ipo_id, "short_code": d.short_code, "list_date": d.listing_date, "offer_price": d.offer_price,
             **{k: v for k, v in asdict(s).items() if k in ROW_COLS}} for d, s in results]


def _line(name, s):
    if not s:
        return f"| {name} | 0 | - | - | - | - | - | - |"
    p = report.pct
    return (f"| {name} | {s['n']} | {p(s['mean'])} | {p(s['median'])} | {s['win_rate'] * 100:.1f}% | "
            f"{p(s['avg_win'])} / {p(s['avg_loss'])} | {p(s['p10'])} | {p(s['worst'])} |")


def _load(start, end):
    mart = config.MART
    facts = facts_from_registry(mart / "dart_ipo_registry.csv", mart / "dart_offer_terms.csv")
    ipo_ids = sorted({f.ipo_id for f in facts if f.var == "listing_date"})
    codes = {f.value_text for f in facts if f.var == "short_code"}
    # 종목 bars + 거래일 달력 + 코스닥 지수(기준선). 민감도 실행까지 색인을 한 번만 만든다
    bars = BarIndex(list(iter_filtered_bars(start, end, codes)) + calendar_bars(start, end)
                    + list(iter_index_bars(start, end)))
    years = sorted({int(f.value_text[:4]) for f in facts if f.var == "listing_date"}) or [2023]
    return facts, ipo_ids, bars, settings.load_costs(years[0], years[-1])


def _summaries(rows):
    usable = [r for r in rows if r["net_ret"] is not None]
    known_not_limit = [r for r in usable if r["buy_at_limit_up"] is False]
    unknown = [r for r in usable if r["buy_at_limit_up"] is None]
    net = lambda rs: report.summarize([r["net_ret"] for r in rs])  # noqa: E731
    return {
        "usable": usable, "n_limit": sum(1 for r in usable if r["buy_at_limit_up"] is True), "n_unknown": len(unknown),
        "summary": net(usable), "summary_ex_limit_up": net(known_not_limit), "summary_unknown": net(unknown),
        "gross": report.summarize([r["gross_ret"] for r in usable]),
        "bench": report.summarize([r["bench_ret"] for r in usable]),
        # 기준선·초과수익은 주 결과와 같은 표본(상한가 아님 확인 건)으로 맞춰 비교한다
        "summary_bench": report.summarize([r["bench_ret"] for r in known_not_limit]),
        "summary_excess": report.summarize([r["net_ret"] - r["bench_ret"] for r in known_not_limit
                                            if r["bench_ret"] is not None]),
        "exit_issues": dict(collections.Counter(r["exit_kind"] for r in rows if r["exit_kind"] != "정상")),
        "summary_last_close": _with_fallback(rows, "net_ret_last_close"),
        "summary_wipeout": _with_fallback(rows, "net_ret_wipeout"),
    }


def _with_fallback(rows, key):
    """주 결과와 같은 기준(상한가 아님 확인 건)에 폐지·거래정지 건을 민감도 값으로 채워 넣은 요약.
    청산일이 아직 오지 않은 건(미도래)은 폐지가 아니므로 넣지 않는다."""
    vals = [r["net_ret"] if r["net_ret"] is not None else r[key] for r in rows
            if r["buy_at_limit_up"] is False and (r["net_ret"] is not None or r[key] is not None)]
    return report.summarize(vals)


def _sensitivity(ipo_ids, facts, bars, costs):
    out = {}
    for slip in costs.get("slippage_sensitivity", []):
        alt = run_a0(ipo_ids, facts, bars, {**costs, "slippage_per_side": slip})
        vals = [s.net_ret for _, s in alt if s.net_ret is not None and s.buy_at_limit_up is False]
        out[slip] = st.mean(vals) if vals else None
    return out


def _write_csv(rows, start, end):
    config.MART.mkdir(parents=True, exist_ok=True)
    path = config.MART / f"a0_real_{start}_{end}.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ROW_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r[k] is None else r[k]) for k in ROW_COLS})
    return path


def _benchmark_text(sm) -> str:
    """코스닥 기준선과 D12 판정 문구. 지수 데이터가 없으면 계산 불가로 적는다. 유의성 검정은 하지 않았다."""
    bench, excess, main = sm["summary_bench"], sm["summary_excess"], sm["summary_ex_limit_up"]
    if not bench or not excess or not main:
        return "계산 불가 — 코스닥 지수 데이터(kosdaq_dd_trd)가 없음 (미수집이거나 서비스 이용 권한 없음)"
    p = report.pct
    ok1, ok2 = main["mean"] > 0, excess["mean"] > 0
    return (f"같은 날 코스닥 종가→익일 시가, 주 결과와 같은 표본 평균 {p(bench['mean'])} (n={bench['n']})\n"
            f"- 종목별 초과수익(순수익 − 기준선) 평균 {p(excess['mean'])}, 중앙값 {p(excess['median'])} (n={excess['n']})\n"
            f"- D12 판정: ① 기대값 > 0: {'예' if ok1 else '아니오'} ({p(main['mean'])}) · "
            f"② 기준선 대비 우위: {'예' if ok2 else '아니오'} ({p(excess['mean'])})\n"
            f"- 통계적 유의성(표준오차·부트스트랩)은 검정하지 않았다. 표본이 작아 평균 차이만으로 결론내리지 말 것.")


def _render_doc(rows, sm, sensitivity, costs):
    dates = sorted(r["list_date"] for r in rows if r["list_date"])
    bench_text = _benchmark_text(sm)
    sens = "\n".join(f"- 편도 {k * 100:.2f}%: {report.pct(v)}" for k, v in sensitivity.items()) or "- 설정 없음"
    issues = sm["exit_issues"]
    issues_text = ", ".join(f"{k} {v}건" for k, v in issues.items()) or "없음 (폐지/거래정지 0건)"
    return f"""# A0 기준선 결과 (실데이터) — 상장일 종가 매수 → 다음 거래일 시가 매도

작성 {date.today()} · 자동 생성 초안 · 근거 D5, D7, D11, D12

## 데이터
- 대상: 코스닥 신규상장 중 DART 지분증권 신고서가 있고 KRX 종목기본정보에 상장일이 있는 종목 (레지스트리 `in_trading_universe`)
- 기간: {dates[0] if dates else '-'} ~ {dates[-1] if dates else '-'} · 대상 {len(rows)}건 · 계산 가능 {len(sm['usable'])}건 · 계산 불가 {len(rows) - len(sm['usable'])}건
- 출처: KRX Open API 코스닥 일별매매정보 (원본 `data/0_raw/krx`), DART 발행조건확정 공시 원문 (확정 공모가)
- 학습/검증 분리: 이 결과는 기준값이 없는 기준선이라 분리하지 않음

## 비용·체결 가정
- 수수료 편도 {costs['commission_per_side'] * 100:.3f}% · 슬리피지 편도 {costs['slippage_per_side'] * 100:.2f}% · 매도 거래세 연도별 {costs['kosdaq_sell_tax']}
- 하룻밤 갭은 시가 체결로 그대로 반영 (D5)
- 상한가 종가(공모가 ×4) {sm['n_limit']}건은 종가 매수 체결이 불확실 → 주 결과에서 제외. 공모가를 몰라 상한가 불명인 건 {sm['n_unknown']}건은 따로 표시
- 주 결과는 상한가가 아님이 확인된 건만, 전부 체결 가정은 민감도

## 성과
| 구분 | 건수 | 평균(기대값) | 중앙값 | 승률 | 평균 수익 / 평균 손실 | 하위 10% | 최대 손실 |
|---|---|---|---|---|---|---|---|
{_line('비용 차감 후 · 상한가 아님 확인(주 결과)', sm['summary_ex_limit_up'])}
{_line('비용 차감 후 · 상한가 불명(공모가 미확인)', sm['summary_unknown'])}
{_line('비용 차감 후 · 전부 체결 가정', sm['summary'])}
{_line('비용 차감 전 · 전부 체결 가정', sm['gross'])}

## 폐지/거래정지/청산 미도래 (생존자 편향 점검)
- 청산 가격이 없는 건: {issues_text}. 이 건들은 주 결과에서 계산 불가로 빠지지만 아래 민감도로 되돌려 넣어 본다.
- 거래정지는 재개 후 첫 시가, 폐지는 마지막 종가로 청산했다고 가정한 값과 전손(-100%) 가정 값이다. 청산 미도래는 넣지 않는다.

| 구분 | 건수 | 평균(기대값) | 중앙값 | 승률 | 평균 수익 / 평균 손실 | 하위 10% | 최대 손실 |
|---|---|---|---|---|---|---|---|
{_line('주 결과 + 폐지/정지 마지막 종가(재개 시가) 청산', sm['summary_last_close'])}
{_line('주 결과 + 폐지/정지 전손(-100%) 가정', sm['summary_wipeout'])}

## 코스닥 기준선
- {bench_text}

## 슬리피지 민감도 (상한가 아님 확인 건 평균, 비용 차감 후)
{sens}

## 한계
- 공모가는 DART 확정 공모가 우선. KRX 역산값은 일부 종목에서 다르다(진코스텍 23,850 vs 23,500).
- 상장일·종목코드는 KRX 종목기본정보(현재 상장 종목 스냅샷)에서 와서 상장폐지된 종목이 빠진다 (생존자 편향).
- 이 결과는 필터가 없는 기준선이다. 표본이 작거나 한두 종목에 좌우되면 중앙값·하위 10%를 같이 볼 것.
"""


def run(end: str, start: str | None = None) -> dict:
    start = start or config.BUFFER_START
    facts, ipo_ids, bars, costs = _load(start, end)
    rows = _rows(run_a0(ipo_ids, facts, bars, costs))
    sm = _summaries(rows)
    sensitivity = _sensitivity(ipo_ids, facts, bars, costs)
    out_csv = _write_csv(rows, start, end)
    out_dir = config.ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    doc = out_dir / f"{date.today()}_A0_real_v1.md"
    doc.write_text(_render_doc(rows, sm, sensitivity, costs), encoding="utf-8")
    return {"rows": rows, "summary": sm["summary"], "summary_ex_limit_up": sm["summary_ex_limit_up"],
            "summary_unknown": sm["summary_unknown"], "exit_issues": sm["exit_issues"],
            "summary_last_close": sm["summary_last_close"], "summary_wipeout": sm["summary_wipeout"],
            "summary_bench": sm["summary_bench"], "summary_excess": sm["summary_excess"],
            "sensitivity": sensitivity, "csv": str(out_csv), "doc": str(doc)}


if __name__ == "__main__":
    end_arg = sys.argv[1] if len(sys.argv) > 1 else "20261026"
    res = run(end_arg)
    print(f"[A0] {res['csv']}\n[A0] {res['doc']}\n[A0] n={res['summary']['n'] if res['summary'] else 0}")
