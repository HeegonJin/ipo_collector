"""기초 통계: 전략을 짜기 전에 신규주의 경쟁률·공모 규모·첫날 유형별 수익률 분포를 본다 (Notion 기획 문서 6장 4번).

매매 규칙이 아니라 기술 통계다. 그래서 비용을 빼지 않은 총수익률이고, 상한가 종가도 빼지 않는다 (체결 가정이 없다).
학습(train) 구간만 쓴다. 검증 구간은 열지 않는다. 구간 경계(100·1000배, 1,500억, 고점 대비 -10%)는 문서의 숫자나 이 문서에서 미리 정한 값이고,
결과를 보고 고치지 않는다 (고치면 새 버전).

  python -m evaluate.basic_stats 20261029
"""
import csv
import statistics as st
from datetime import date
from pathlib import Path

import config
from core import settings
from evaluate import splits as splitlib
from evaluate.outcomes import BarIndex, _net
from store.bars import INDEX_CODE, calendar_bars, iter_filtered_bars, iter_index_bars

MIN_N = 10                                   # 문서: 한 조건에 10건 미만이면 결론을 내지 않는다
DEMAND_CUTS = (100.0, 1000.0)                # 기관 경쟁률: 인제니아 <100, 관습적 흥행 1,000:1
SIZE_CUT_BIL = 1500.0                        # 공모 규모 1,500억
NEAR_HIGH = -10.0                            # 종가가 당일 고점 대비 이 값 이상이면 '고점 근처'
HORIZONS = {"1주(D+5)": 5, "1개월(D+21)": 21, "3개월(D+63)": 63, "6개월(D+126)": 126}
MEASURES = ["첫날(공모가 대비 종가)", "익일 시가(D0종가→D1시가)", *HORIZONS]


def _f(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def _read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def offer_size_bil(registry_row: dict, terms: list[dict]) -> float | None:
    """공모 규모(억원) = 확정 공모가 × 상장 전 마지막 공시의 모집 주식수. 구주매출·오버알로트먼트는 따로 구분하지 못한다."""
    price = _f(registry_row.get("offer_price_final"))
    shares = None
    for t in terms:
        if t.get("rcept_dt", "99999999") <= registry_row["list_dd"] and _f(t.get("stock_cnt")):
            shares = _f(t["stock_cnt"])
    return price * shares / 1e8 if price and shares else None


def first_day_type(open_px, close_px, high_px, offer) -> int | None:
    """아이디에이션 2×2: 1 시초가>공모가·고점 근처 / 2 시초가>공모가·고점서 밀림 / 3 시초가≤공모가·고점 근처 / 4 시초가≤공모가·고점서 밀림."""
    if not (open_px and close_px and high_px and offer):
        return None
    high_open = open_px > offer
    near = (close_px / high_px - 1) * 100 >= NEAR_HIGH
    return (1 if near else 2) if high_open else (3 if near else 4)


def _net_ret(exit_px: float, entry_px: float, costs: dict, year: int) -> float:
    """A0 와 같은 비용 공식 (수수료·슬리피지 편도, 연도별 매도세)."""
    tax = costs["kosdaq_sell_tax"]
    if year not in tax:
        raise ValueError(f"매도세율이 없는 연도: {year}")
    return _net(exit_px, entry_px, (costs["commission_per_side"], costs["slippage_per_side"], tax[year])) * 100


def build_rows(universe: list[dict], terms_by_ipo: dict, demand: dict, index: BarIndex, splits: dict, split: str = "train",
               costs: dict | None = None) -> list[dict]:
    """costs 를 주면 기간 수익률마다 비용 차감 후 값(`이름|순`)도 계산한다 (상장일 종가 매수 → D+N 종가 매도)."""
    idx = index.code(INDEX_CODE)
    rows = []
    for r in universe:
        d0, offer = r["list_dd"], _f(r["offer_price_final"])
        if not splitlib.in_split(d0, split, splits):
            continue
        bars = index.code(r["stock_code"])
        b0 = bars.get(d0)
        if not b0 or not offer or not b0.get("close"):
            continue
        c0 = b0["close"]
        meas = {MEASURES[0]: (c0 / offer - 1) * 100}
        d1 = index.day_after(d0, 1)
        meas[MEASURES[1]] = (bars[d1]["open"] / c0 - 1) * 100 if d1 in bars and bars[d1].get("open") else None
        i0 = idx.get(d0)
        for name, k in HORIZONS.items():
            dk = index.day_after(d0, k)
            bk, ik = bars.get(dk), idx.get(dk)
            if bk and bk.get("close") and i0 and ik and i0.get("close") and ik.get("close"):
                s, m = (bk["close"] / c0 - 1) * 100, (ik["close"] / i0["close"] - 1) * 100
                meas[name], meas[name + "|초과"] = s, s - m
                if costs:
                    meas[name + "|순"] = _net_ret(bk["close"], c0, costs, int(d0[:4]))
            else:
                meas[name] = meas[name + "|초과"] = None
            if costs and name + "|순" not in meas:
                meas[name + "|순"] = None
        dem = demand.get(r["ipo_id"], {})
        rows.append({
            "name": r["corp_name"], "list_date": d0, "measures": meas,
            "demand_ratio": _f(dem.get("demand_ratio")) if dem.get("demand_status") == "확인" else None,
            "size_bil": offer_size_bil(r, terms_by_ipo.get(r["ipo_id"], [])),
            "type": first_day_type(b0.get("open"), c0, b0.get("high"), offer),
        })
    return rows


def _bucket_demand(v):
    if v is None:
        return "값 없음(미확인·미수집)"
    return f"{DEMAND_CUTS[0]:.0f}배 미만" if v < DEMAND_CUTS[0] else (
        f"{DEMAND_CUTS[0]:.0f}~{DEMAND_CUTS[1]:.0f}배 미만" if v < DEMAND_CUTS[1] else f"{DEMAND_CUTS[1]:.0f}배 이상")


def _bucket_size(v):
    return "값 없음" if v is None else (f"{SIZE_CUT_BIL:.0f}억 미만" if v < SIZE_CUT_BIL else f"{SIZE_CUT_BIL:.0f}억 이상")


TYPE_LABEL = {1: "1번 시초>공모가·고점 근처", 2: "2번 시초>공모가·고점서 밀림",
              3: "3번 시초≤공모가·고점 근처", 4: "4번 시초≤공모가·고점서 밀림", None: "값 없음"}
GROUPINGS = [
    ("전체", lambda r: "전체"),
    ("기관 수요예측 경쟁률", lambda r: _bucket_demand(r["demand_ratio"])),
    ("공모 규모", lambda r: _bucket_size(r["size_bil"])),
    ("첫날 유형 (2×2)", lambda r: TYPE_LABEL[r["type"]]),
]


def cell(vals: list[float]) -> str:
    if not vals:
        return "-"
    if len(vals) < MIN_N:
        return f"표본 부족 (n={len(vals)})"
    return f"{st.mean(vals):+.1f}% / {st.median(vals):+.1f}% (n={len(vals)})"


def _table(rows: list[dict], key, measures: list[str], excess: bool) -> list[str]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    head = "| 구분 | 건수 | " + " | ".join(measures) + " |"
    out = [head, "|" + "---|" * (len(measures) + 2)]
    for g in sorted(groups):
        rs = groups[g]
        cells = []
        for m in measures:
            k = m + "|초과" if excess and m in HORIZONS else m
            cells.append(cell([r["measures"][k] for r in rs if r["measures"].get(k) is not None]))
        out.append(f"| {g} | {len(rs)} | " + " | ".join(cells) + " |")
    return out


def net_cell(vals: list[float]) -> str:
    """평균 / 중앙값 / 승률 (n). 승률은 비용 차감 후 수익이 0 초과인 비율."""
    if not vals:
        return "-"
    if len(vals) < MIN_N:
        return f"표본 부족 (n={len(vals)})"
    wins = sum(v > 0 for v in vals) / len(vals)
    return f"{st.mean(vals):+.1f}% / {st.median(vals):+.1f}% / 승률 {wins * 100:.0f}% (n={len(vals)})"


def _net_table(rows: list[dict], key) -> list[str]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    out = ["| 구분 | 건수 | " + " | ".join(HORIZONS) + " |", "|" + "---|" * (len(HORIZONS) + 2)]
    for g in sorted(groups):
        cells = [net_cell([r["measures"][n + "|순"] for r in groups[g] if r["measures"].get(n + "|순") is not None]) for n in HORIZONS]
        out.append(f"| {g} | {len(groups[g])} | " + " | ".join(cells) + " |")
    return out


def render(rows: list[dict], start: str, end: str, split_text: str) -> str:
    L = ["# 기초 통계 (학습 구간) — 경쟁률·공모 규모·첫날 유형별 수익률 분포", "",
         f"작성 {date.today()} · 자동 생성 초안 · 근거 Notion 기획 문서(아이디에이션) 6장 4번, 설계 v2 검증 원칙", "",
         "## 데이터",
         f"- 대상: 레지스트리 `in_trading_universe` 중 {split_text} 상장 종목 · {len(rows)}건 (상장일 시세·확정 공모가가 있는 건)",
         f"- 기간: 시세 {start} ~ {end} (장기 수익률은 이후 거래일이 모자라면 해당 칸만 제외)",
         "- 출처: KRX Open API 코스닥 일별매매정보·KOSDAQ 시리즈, DART 발행조건확정·증권발행실적보고서",
         "- 이 문서는 **KRX statistical information** (한국거래소 통계정보)을 이용해 만들었다 (KRX OPEN API 약관 Art.10(3)). "
         "원천 데이터는 비상업 목적으로만 쓰며 제3자에게 제공하지 않는다 (Art.6(2), Art.11(2)).",
         "- 학습/검증 분리: 학습(train)만 사용했다. 검증 구간은 열지 않았다.", "",
         "## 가정",
         "- 기술 통계다. **비용(수수료·슬리피지·세금)을 빼지 않은 총수익률**이고, 상한가 종가도 제외하지 않았다. 매매 성과로 읽지 말 것.",
         "- 기간 수익률은 상장일 종가 기준이다 (D+5·21·63·126 거래일 뒤 종가). 초과수익은 같은 기간 코스닥 지수 수익률을 뺀 값이다.",
         f"- 칸 형식: 평균 / 중앙값 (n). 구간별 n이 {MIN_N} 미만이면 숫자를 내지 않는다 (설계 문서의 '10건 미만이면 결론 없음').",
         f"- 구간 경계는 문서의 숫자(경쟁률 100·1,000배, 공모 {SIZE_CUT_BIL:.0f}억)와 이 문서에서 미리 정한 값(고점 근처 = 종가가 당일 고점 대비 {NEAR_HIGH:.0f}% 이상)이다. 결과를 보고 고치지 않았다.",
         "- 공모 규모 = 확정 공모가 × 상장 전 마지막 공시의 모집 주식수. 구주매출·오버알로트먼트를 따로 구분하지 못한다.",
         "- 경쟁률은 교차 검증을 통과(확인)한 값만 쓴다. 못 읽은 종목은 '값 없음'으로 따로 센다 (0으로 채우지 않음).", "",
         "## 첫날·익일 (총수익률)"]
    for title, key in GROUPINGS:
        L += ["", f"### {title}"] + _table(rows, key, MEASURES[:2], False)
    L += ["", "## 상장 후 기간 수익률 — 코스닥 대비 초과수익 (D0 종가 기준, 총수익률)"]
    for title, key in GROUPINGS:
        L += ["", f"### {title}"] + _table(rows, key, list(HORIZONS), True)
    if any("1주(D+5)|순" in r["measures"] for r in rows):
        L += ["", "## 기간 청산 후보 — 상장일 종가 매수 → D+N 종가 매도 (비용 차감 후)",
              "전략 B·C의 청산 규칙 후보를 정하기 전에 보는 참고용이다. 매수 조건(시장 반등, 락업 해제 등)은 쓰지 않은 '조건 없이 산 경우'라 B·C의 성과가 아니다. "
              "수수료·슬리피지(편도)·연도별 매도세를 뺐고 종가로 팔았다고 가정했다. 칸 형식: 평균 / 중앙값 / 승률 (n)."]
        for title, key in GROUPINGS:
            L += ["", f"### {title}"] + _net_table(rows, key)
    L += ["", "## 읽을 때 주의",
          "- 표본이 작고 구간을 여러 개 비교하므로 우연히 큰 차이가 날 수 있다. 통계적 유의성은 검정하지 않았다.",
          "- 구간 평균은 이상치(상한가 직행 등)에 크게 흔들린다. 평균과 중앙값이 크게 다르면 중앙값을 먼저 볼 것.",
          "- 이 표만으로 전략을 채택하지 않는다. 후보를 고르면 사람이 새 버전 config로 고정하고 forward 구간에서 확인한다 (D9)."]
    return "\n".join(L) + "\n"


def run(end: str, start: str | None = None, split: str = "train", splits: dict | None = None, out_dir: Path | None = None) -> dict:
    if split == "valid":
        raise ValueError("기초 통계는 검증 구간을 열지 않는다 (valid 는 한 번만 연다)")
    start = start or config.BUFFER_START
    splits = splits or settings.load_splits()
    mart = config.MART
    universe = [r for r in _read(mart / "dart_ipo_registry.csv") if r["in_trading_universe"] == "True" and r["list_dd"]]
    terms: dict[str, list[dict]] = {}
    for t in _read(mart / "dart_offer_terms.csv"):
        terms.setdefault(t["ipo_id"], []).append(t)
    demand = {r["ipo_id"]: r for r in _read(mart / "dart_demand.csv")} if (mart / "dart_demand.csv").exists() else {}
    codes = {r["stock_code"] for r in universe}
    index = BarIndex(list(iter_filtered_bars(start, end, codes)) + calendar_bars(start, end) + list(iter_index_bars(start, end)))
    years = sorted({int(r["list_dd"][:4]) for r in universe}) or [2023]
    rows = build_rows(universe, terms, demand, index, splits, split, settings.load_costs(years[0], years[-1]))
    s, e = splitlib.window(split, splits)
    split_text = f"{split} ({s}~{'계속' if e == '99991231' else e}, 상장일 기준)"
    out_dir = out_dir or config.ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    doc = out_dir / f"{date.today()}_기초통계_{split}_v1.md"
    doc.write_text(render(rows, start, end, split_text), encoding="utf-8")
    return {"rows": rows, "doc": str(doc)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="기초 통계 (경쟁률·공모 규모·첫날 유형별 수익률 분포)")
    ap.add_argument("end", nargs="?", default="20261026")
    ap.add_argument("--split", default="train", choices=("train", "forward", "all"))
    a = ap.parse_args()
    res = run(a.end, split=a.split)
    print(f"[기초통계] n={len(res['rows'])}  {res['doc']}")
