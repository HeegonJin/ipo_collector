"""
첫 실험 결과 문서 (results/README 형식).
  파일: results/YYYY-MM-DD_first-experiment_v1.md
  필수: 데이터 기간, 비용·슬리피지·갭 가정, 기대값·승률·평균 수익/손실·최대 손실폭, 기준선 비교
"""
import csv
import statistics as st
from datetime import date
from pathlib import Path

import config


def _f(x):
    return None if x in ("", None) else float(x)


def percentile(vals, q: float) -> float:
    """선형보간 백분위수 (q: 0~1). 표본이 작아도 최솟값으로 쏠리지 않는다."""
    s = sorted(vals)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def summarize(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    return {
        "n": len(vals),
        "mean": st.mean(vals),
        "median": st.median(vals),
        "win_rate": len(wins) / len(vals),
        "avg_win": st.mean(wins) if wins else 0.0,
        "avg_loss": st.mean(losses) if losses else 0.0,
        "worst": min(vals),
        "p10": percentile(vals, 0.10),
    }


def pct(x):
    return "-" if x is None else f"{x * 100:+.2f}%"


def write(sample_csv: Path):
    rows = [r for r in csv.DictReader(open(sample_csv, encoding="utf-8-sig")) if not r["excluded"]]
    usable = [r for r in rows if r["net_ret"] not in ("", None)]
    net = summarize([_f(r["net_ret"]) for r in usable])
    gross = summarize([_f(r["gross_ret"]) for r in usable])
    idx = summarize([_f(r["kosdaq_overnight"]) for r in usable])
    limit_up = sum(1 for r in usable if r["buy_at_limit_up"] == "True")

    def line(name, s):
        if not s:
            return f"| {name} | 0 | - | - | - | - | - | - |"
        return (f"| {name} | {s['n']} | {pct(s['mean'])} | {pct(s['median'])} | {s['win_rate']*100:.1f}% | "
                f"{pct(s['avg_win'])} / {pct(s['avg_loss'])} | {pct(s['p10'])} | {pct(s['worst'])} |")

    dates = sorted(r["list_date"] for r in rows)
    verdict = "판정 불가 (표본 없음)"
    if net and idx:
        ok1, ok2 = net["mean"] > 0, net["mean"] > idx["mean"]
        verdict = (f"① 기대값 > 0: {'예' if ok1 else '아니오'} ({pct(net['mean'])}) · "
                   f"② 코스닥 종가→익일 시가 대비 우위: {'예' if ok2 else '아니오'} ({pct(idx['mean'])})")

    md = f"""# 첫 실험 결과 — 상장 첫날 종가 매수 → 다음 날 시가 매도

작성 {date.today()} · 담당 진 · 근거 D5, D7, D11, D12 · 상태: 자동 생성 초안

## 판정 (D12 성공 기준)
{verdict}

## 데이터
- 대상: 코스닥 신규상장 (스팩·리츠·코넥스 이전상장 제외, 공모 공시 없는 상장 제외는 DART 단계 적용 여부 확인)
- 기간: {dates[0] if dates else '-'} ~ {dates[-1] if dates else '-'} · 대상 {len(rows)}건 · 계산 가능 {len(usable)}건
- 학습/검증 분리: 첫 실험은 고를 값이 없어 분리하지 않음 (CHARTER)
- 출처: KRX Open API 코스닥 일별매매정보·KOSDAQ 지수 일별시세 (원본 `data/0_raw/krx`)

## 비용·체결 가정
- 수수료 편도 {config.COMMISSION_PER_SIDE*100:.3f}% · 슬리피지 편도 {config.SLIPPAGE_PER_SIDE*100:.2f}% · 매도 거래세 연도별 {config.KOSDAQ_SELL_TAX}
- 하룻밤 갭은 시가 체결로 그대로 반영. 손절로 막지 않음 (D5)
- 상장일 종가가 상한가(공모가 ×4)인 {limit_up}건은 종가 매수 체결이 불확실 → 포함한 값이며 별도 확인 필요

## 성과
| 구분 | 건수 | 평균(기대값) | 중앙값 | 승률 | 평균 수익 / 평균 손실 | 하위 10% | 최대 손실 |
|---|---|---|---|---|---|---|---|
{line('비용 차감 후', net)}
{line('비용 차감 전', gross)}
{line('기준선: 같은 날 코스닥 종가→익일 시가', idx)}

## 한계
- 종가 매수 판단은 장 마감 전 자료로 해야 하나, 여기서는 확정 종가를 안다고 가정 (조건 없는 전 종목 매수라 판단 자료가 없으므로 영향 없음. 필터 전략부터는 문제)
- 공모가는 상장일 기준가로 역산한 값. DART 증권발행실적보고서와 대조 전
- 표본 수가 작으면 평균이 한두 종목에 좌우됨 → 중앙값·하위 10% 같이 볼 것
"""
    out_dir = config.ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{date.today()}_first-experiment_v1.md"
    out.write_text(md, encoding="utf-8")
    print(f"[결과] {out}")
    return out


if __name__ == "__main__":
    import sys
    write(Path(sys.argv[1]))
