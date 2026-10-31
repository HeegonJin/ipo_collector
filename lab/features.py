"""전략 실험 앱의 추가 조건 계산: 시장 온도(M1), 코스닥 지수 추세(M4), 업종 강도(M3), 구주매출 비중(M1).

모두 '조건 슬라이더'로 쓰는 숫자다. 설계 문서에 기준이 없어 임계값은 사람이 앱에서 조절하며 찾는다 (그래서 화면에 '설계도 외 탐색').
상장 전(pre)에 쓸 수 있는 값은 상장일 전날까지의 자료만 읽는다 — 시계열은 모두 `day` 보다 이른 날짜만 쓴다.
값을 못 구하면(자료 부족·매핑 없음·교차검증 실패) 0 이 아니라 None 이다.

한계: 업종지수 대응은 현재 DART 업종코드(상장 후 바뀌었을 수 있음) → config/sector_map_v1.yaml (Claude 제안) 이고,
KRX 업종지수 중 'IT 서비스'·'통신' 은 2026년 자료에만 있어 이전 상장분은 계산 불가가 된다.
"""
import statistics as st
from bisect import bisect_left
from datetime import datetime, timedelta

HEAT_N = 5            # 직전 N개 신규상장의 평균 상장일 수익률
HEAT_DAYS = 30        # 직전 30 달력일의 신규상장 건수
RET_WINDOWS = (20, 60)
DD_WINDOW, VOL_WINDOW, SECTOR_WINDOW = 60, 20, 20


class Series:
    """날짜순 (date, close). day 이전 값만 돌려주는 조회를 제공한다."""

    def __init__(self, points: dict):
        pts = sorted((d, c) for d, c in points.items() if c)
        self.dates = [d for d, _ in pts]
        self.closes = [c for _, c in pts]

    def last_before(self, day: str) -> int | None:
        i = bisect_left(self.dates, day) - 1
        return i if i >= 0 else None

    def trailing_ret(self, day: str, n: int) -> float | None:
        i = self.last_before(day)
        return (self.closes[i] / self.closes[i - n] - 1) * 100 if i is not None and i - n >= 0 else None

    def drawdown(self, day: str, n: int) -> float | None:
        i = self.last_before(day)
        if i is None or i - n + 1 < 0:
            return None
        return (self.closes[i] / max(self.closes[i - n + 1:i + 1]) - 1) * 100

    def volatility(self, day: str, n: int) -> float | None:
        """최근 n 일 일간 수익률(%)의 표준편차."""
        i = self.last_before(day)
        if i is None or i - n < 0:
            return None
        w = self.closes[i - n:i + 1]
        return st.stdev([(b / a - 1) * 100 for a, b in zip(w, w[1:])])


def sector_name(induty_code: str | None, cfg: dict) -> str | None:
    if not induty_code:
        return None
    p = str(induty_code)[:2]
    if p in cfg["map"]:
        return cfg["map"][p]
    return cfg["fallback_manufacturing"] if p.isdigit() and 10 <= int(p) <= 33 else cfg["fallback_other"]


def ipo_heat(history: list[dict], day: str) -> dict:
    """history: [{'list_date','ret'}] (ret = 상장일 종가의 공모가 대비 %). day 보다 먼저 상장한 것만 쓴다."""
    prior = sorted((h for h in history if h["list_date"] < day), key=lambda h: h["list_date"])
    cutoff = (datetime.strptime(day, "%Y%m%d") - timedelta(days=HEAT_DAYS)).strftime("%Y%m%d")
    return {
        "ipo_heat_ret5": sum(h["ret"] for h in prior[-HEAT_N:]) / HEAT_N if len(prior) >= HEAT_N else None,
        "ipo_heat_cnt30": sum(1 for h in prior if h["list_date"] >= cutoff) if prior else None,
    }


def secondary_pct(estk: dict | None, list_dd: str) -> float | None:
    """구주매출 비중(%) = 매출인이 파는 주식 수 ÷ 모집(매출) 주식 수. 상장일 전에 접수된 가장 늦은 신고서 기준.
    매출인 표가 아예 없으면 구주매출이 없는 것(0%)으로 본다. 합계가 맞지 않으면 None (미확인)."""
    if not estk:
        return None
    groups = {g.get("title"): g.get("list", []) for g in (estk.get("resp") or {}).get("group", [])}
    kinds = [r for r in groups.get("증권의종류", []) if str(r.get("rcept_no", ""))[:8] <= list_dd]
    if not kinds:
        return None
    latest = max(r["rcept_no"] for r in kinds)
    total = _sum(r.get("stkcnt") for r in kinds if r["rcept_no"] == latest)
    if not total:
        return None
    sold = _sum(r.get("slstk") for r in groups.get("매출인에관한사항", []) if r["rcept_no"] == latest) or 0.0
    return sold / total * 100 if sold <= total else None


def _sum(values) -> float | None:
    nums = []
    for v in values:
        s = str(v).replace(",", "").strip() if v is not None else ""
        if s not in ("", "-"):
            try:
                nums.append(float(s))
            except ValueError:
                pass
    return sum(nums) if nums else None


def build_extra(universe: list[dict], history: list[dict], index_series: dict[str, Series], estk: dict[str, dict],
                induty: dict[str, str], sector_cfg: dict) -> dict[str, dict]:
    """{ipo_id: {새 조건 값}}. index_series: {'코스닥': Series, '제조': Series, ...}."""
    kosdaq = index_series.get("코스닥")
    out = {}
    for r in universe:
        day, f = r["list_dd"], {}
        f.update(ipo_heat(history, day))
        for n in RET_WINDOWS:
            f[f"idx_ret{n}"] = kosdaq.trailing_ret(day, n) if kosdaq else None
        f["idx_dd60"] = kosdaq.drawdown(day, DD_WINDOW) if kosdaq else None
        f["idx_vol20"] = kosdaq.volatility(day, VOL_WINDOW) if kosdaq else None
        name = sector_name(induty.get(r["corp_code"]), sector_cfg)
        sec = index_series.get(name) if name else None
        f["sector_ret20"] = sec.trailing_ret(day, SECTOR_WINDOW) if sec else None
        f["sector_rel20"] = (f["sector_ret20"] - f["idx_ret20"]) if f["sector_ret20"] is not None and f["idx_ret20"] is not None else None
        f["secondary_pct"] = secondary_pct(estk.get(r["corp_code"]), day)
        out[r["ipo_id"]] = f
    return out
