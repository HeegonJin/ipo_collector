"""일일 판단 작업: 모의 운영 장부(data/ledger/paper_a0.jsonl)에 판단을 기록하고 정산한다.

하루 순서
  1) 전날 저녁~당일 아침  python krx_api.py <어제>             # 전 거래일 시세 수집 (공개는 다음 거래일 08:00 로 가정, 실측 중)
  2) 08:30~08:35          python -m ops.daily_job swing <오늘>   # 전략 B·C: 어제까지의 일봉으로 판단 → 오늘 시가 매수
  3) 15:20~15:25          python -m ops.daily_job a0 <오늘>      # A0 기준선: 오늘 상장하는 종목(수기 일정)을 상장일 종가에 매수
  4) 저녁                 python -m ops.daily_job settle <수집된 마지막 날>   # 청산일이 지난 판단을 정산
  (상장 일정은 사전에 python -m ops.schedule add 로 적어 둔다)

판단 시각 +5분 뒤에 장부에 쓰면 그 행은 무효(valid=false)로 남는다 (사후 판단 방지). 그래서 정해진 시각 직후에 실행해야 한다.
판단 코드는 백테스트와 같은 strategies/ 를 PitReader 로만 읽는다.
"""
import sys
from datetime import datetime, timedelta

import config
from core import settings
from core.pit import PitReader
from core.tradingcal import KST
from decide.runner import Decision, run_decision_point
from ledger.ledger import Ledger
from ops import schedule
from ops.paper_ledger import LEDGER_PATH, record_decisions, record_unmapped, settle_from_raw
from store.bars import INDEX_CODE, iter_filtered_bars, iter_index_bars
from store.facts import facts_from_demand_mart, facts_from_registry
from strategies import b, c

LOOKBACK_DAYS = 330        # B 는 상장 후 120거래일, C 는 6개월 해제+관찰까지 보므로 이 정도 이전 상장까지 훑는다


def a0_as_of(day: str) -> datetime:
    return datetime.strptime(day, "%Y%m%d").replace(hour=15, minute=20, tzinfo=KST)


def swing_as_of(day: str) -> datetime:
    return datetime.strptime(day, "%Y%m%d").replace(hour=8, minute=30, tzinfo=KST)


def decide_a0(day: str, entries: list, registry_rows: list[dict], ledger: Ledger, wallclock: datetime) -> list[dict]:
    """오늘 상장하는 (수기 입력된) 종목마다 A0 판단. 결과를 모두 돌려주고, 매수는 장부에 기록한다 (관망 중 DART 미연결은 임시 id 로 기록)."""
    as_of = a0_as_of(day)
    seen, report, facts, ipo_ids, unmapped, names = set(), [], [], [], [], {}
    for e in entries:
        if e.list_date != day or e.stock_code in seen:
            continue
        seen.add(e.stock_code)
        row = schedule.match_registry(e, registry_rows)
        if row is None:
            unmapped.append({"code": e.stock_code, "name": e.corp_name, "list_date": day})
            report.append({"strategy": "A0", "name": e.corp_name, "action": "관망", "reasons": ["DART 레지스트리에서 못 찾음 (장부에는 미연결로 기록)"], "recorded": True})
            continue
        ipo_ids.append(row["ipo_id"])
        names[row["ipo_id"]] = e.corp_name
        facts += schedule.facts_for(e, row["ipo_id"], row)
    decisions = run_decision_point(as_of, ipo_ids, facts, [])
    record_decisions(ledger, decisions, wallclock)
    record_unmapped(ledger, unmapped, as_of, wallclock)
    late = wallclock > as_of + timedelta(minutes=5)
    for d in decisions:
        report.append({"strategy": d.strategy, "name": names[d.ipo_id], "action": d.action, "reasons": list(d.reasons),
                       "recorded": d.action == "매수", "late": late and d.action == "매수"})
    return report


def _buys_so_far(ledger: Ledger) -> set:
    out = set()
    for r in ledger.rows():
        if r["type"] == "decision" and r["action"] == "매수" and r["valid"]:
            tag = r["reasons"][0] if r["strategy"] == c.NAME else ""
            out.add((r["ipo_id"], r["strategy"], tag))
    return out


def decide_swing(day: str, universe: list[dict], facts: list, bars: list[dict], ledger: Ledger, wallclock: datetime) -> list[dict]:
    """상장 후 이미 시간이 지난 종목마다 B·C 신호를 본다. 신호는 그날(어제까지의 일봉으로) 한 번만 기록하고,
    B 는 종목당 한 번, C 는 해제 사건(기간)마다 한 번만 진입한다."""
    as_of = swing_as_of(day)
    by_code: dict[str, list] = {}
    for bar in bars:
        by_code.setdefault(bar["short_code"], []).append(bar)
    index_bars = by_code.get(INDEX_CODE, [])
    facts_by_ipo: dict[str, list] = {}
    for f in facts:
        facts_by_ipo.setdefault(f.ipo_id, []).append(f)
    done = _buys_so_far(ledger)
    report, decisions = [], []
    for row in universe:
        if not row["list_dd"] or row["list_dd"] >= day:
            continue
        reader = PitReader(facts_by_ipo.get(row["ipo_id"], []), by_code.get(row["stock_code"], []) + index_bars, as_of)
        for module in (b, c):
            sig = module.evaluate(reader, row["ipo_id"], settings.load_strategy(module.NAME))
            if sig.action != "매수":
                continue
            tag = sig.reasons[0] if module is c else ""
            dup = (row["ipo_id"], module.NAME, tag) in done or (module is b and any(k[0] == row["ipo_id"] and k[1] == b.NAME for k in done))
            item = {"strategy": module.NAME, "name": row["corp_name"], "action": "매수", "reasons": list(sig.reasons), "recorded": not dup}
            if dup:
                item["reasons"].append("이미 진입한 종목·사건이라 기록하지 않음")
            else:
                decisions.append(Decision(row["ipo_id"], module.NAME, as_of, "매수", "next_open", module.NAME, sig.reasons,
                                          sig.short_code, sig.listing_date, sig.offer_price))
            report.append(item)
    record_decisions(ledger, decisions, wallclock)
    return report


# ── 실데이터 진입점 ─────────────────────────────────────────────
def previous_weekday(day: str) -> str:
    d = datetime.strptime(day, "%Y%m%d").date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def run_swing(day: str, allow_stale: bool = False, wallclock: datetime | None = None) -> list[dict]:
    prev = previous_weekday(day)
    if not allow_stale and not (config.RAW / "krx" / "ksq_daily" / f"{prev}.json").exists():
        raise SystemExit(f"전 거래일({prev}) KRX 일별 자료가 없습니다. 먼저 python krx_api.py {prev} 를 실행하세요 "
                         "(휴장일이라 파일이 없다면 --allow-stale).")
    mart = config.MART
    reg = schedule.registry_rows()
    universe = [r for r in reg if r["in_trading_universe"] == "True" and r["list_dd"]]
    start = (datetime.strptime(day, "%Y%m%d") - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    universe = [r for r in universe if r["list_dd"] >= start]
    end = (datetime.strptime(day, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    codes = {r["stock_code"] for r in universe}
    bars = list(iter_filtered_bars(start, end, codes)) + list(iter_index_bars(start, end))
    facts = facts_from_registry(mart / "dart_ipo_registry.csv", mart / "dart_offer_terms.csv") + \
        facts_from_demand_mart(mart / "dart_demand.csv")
    return decide_swing(day, universe, facts, bars, Ledger(LEDGER_PATH), wallclock or datetime.now(KST))


def run_a0(day: str, wallclock: datetime | None = None) -> list[dict]:
    return decide_a0(day, schedule.load(), schedule.registry_rows(), Ledger(LEDGER_PATH), wallclock or datetime.now(KST))


def missing_listing_bars(ledger: Ledger, end: str) -> list[str]:
    """A0 매수 판단인데 상장일 시세가 없는 종목: 수기로 적은 종목코드가 틀렸을 가능성이 크다."""
    buys = [r for r in ledger.rows() if r["type"] == "decision" and r["action"] == "매수" and r["valid"]
            and r["strategy"] == "A0" and r["listing_date"] <= end]
    if not buys:
        return []
    start = min(r["listing_date"] for r in buys)
    have = {(b_["short_code"], b_["date"]) for b_ in iter_filtered_bars(start, end, {r["short_code"] for r in buys})}
    return [f"{r['short_code']} ({r['listing_date']})" for r in buys if (r["short_code"], r["listing_date"]) not in have]


def print_report(rows: list[dict]) -> None:
    if not rows:
        print("대상 없음")
    for r in rows:
        mark = "기록" if r["recorded"] else "미기록"
        print(f"[{r['strategy']}] {r['name']}: {r['action']} ({mark}) — {'; '.join(r['reasons'])}")
        if r.get("late"):
            print("    [경고] 판단 시각 +5분 뒤에 기록돼 장부에서 무효(valid=false)로 남았습니다.")


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    usage = "사용: python -m ops.daily_job {a0|swing} YYYYMMDD [--allow-stale]  |  settle YYYYMMDD"
    if len(argv) < 2 or argv[0] not in ("a0", "swing", "settle"):
        print(usage)
        return 2
    cmd, day = argv[0], argv[1]
    datetime.strptime(day, "%Y%m%d")
    if cmd == "a0":
        print_report(run_a0(day))
    elif cmd == "swing":
        print_report(run_swing(day, "--allow-stale" in argv))
    else:
        led = Ledger(LEDGER_PATH)
        n = settle_from_raw(led, day, datetime.now(KST))
        print(f"[장부] 정산 {n}건 추가, 무결성 문제 {led.verify() or '없음'}")
        bad = missing_listing_bars(led, day)
        if bad:
            print(f"[경고] 상장일 시세가 없는 A0 매수 종목(종목코드 입력 오류 의심): {', '.join(bad)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
