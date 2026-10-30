"""모의 운영 장부 흐름: 판단을 장부에 기록하고, 청산일이 지나면 정산을 추가한다 (L7).

  record_decisions  : 매수 판단만 기록 (관망은 매일 수백 건이라 잡음이다). 같은 판단은 한 행.
  record_unmapped   : 상장은 탐지됐는데 DART 와 연결되지 않은 종목을 임시 id(K:코드_상장일)의 '관망' 판단으로 남긴다.
                      조용히 빠지지 않고 장부에 남게 하려는 것이다.
  settle_due        : 청산일이 지난 매수 판단을 정산해 추가한다. 청산일이 아직 오지 않은 건(미도래)과
                      판단 시각 +5분 뒤에 기록돼 무효가 된 건은 건드리지 않는다. 폐지·거래정지는 사유와 함께 기록한다.
"""
from datetime import datetime

from core import settings
from core.ids import make_temp_ipo_id
from decide.runner import Decision
from evaluate.outcomes import BarIndex, settle
from ledger.ledger import Ledger
from store.bars import calendar_bars, iter_filtered_bars, iter_index_bars
from strategies import a0


def record_decisions(ledger: Ledger, decisions: list[Decision], wallclock: datetime) -> list[str]:
    return [ledger.append_decision(d, wallclock) for d in decisions if d.action == "매수"]


def record_unmapped(ledger: Ledger, unmapped: list[dict], as_of: datetime, wallclock: datetime) -> list[str]:
    """unmapped: [{'code', 'name', 'list_date'}] — KRX 가 신규상장으로 탐지했지만 DART 회사코드와 연결되지 않은 종목."""
    out = []
    for u in unmapped:
        d = Decision(make_temp_ipo_id(u["code"], u["list_date"]), a0.NAME, as_of, "관망", a0.ENTRY_RULE, a0.EXIT_RULE,
                     (f"DART 미연결: {u['name']}",), u["code"], u["list_date"], None)
        out.append(ledger.append_decision(d, wallclock))
    return out


def decision_from_row(row: dict) -> Decision:
    return Decision(row["ipo_id"], row["strategy"], datetime.fromisoformat(row["as_of"]), row["action"],
                    row["entry_rule"], row["exit_rule"], tuple(row["reasons"]), row["short_code"],
                    row["listing_date"], row["offer_price"])


def settle_due(ledger: Ledger, index: BarIndex, costs: dict, settled_at: datetime) -> int:
    """정산을 추가한 건수. costs 는 settings.load_costs(...) 결과 (연도별 매도세를 포함해야 한다)."""
    rows = ledger.rows()
    done = {r["ledger_id"] for r in rows if r["type"] == "settlement"}
    n = 0
    for r in rows:
        if r["type"] != "decision" or r["action"] != "매수" or not r["valid"] or r["ledger_id"] in done:
            continue
        s = settle(decision_from_row(r), index, costs)
        if s.exit_kind == "미도래":
            continue
        ledger.append_settlement(r["ledger_id"], s, settled_at)
        n += 1
    return n


def costs_for(rows: list[dict]) -> dict:
    """장부의 매수 판단이 걸친 연도를 모두 덮는 비용 설정."""
    years = sorted({int(r["listing_date"][:4]) for r in rows if r["type"] == "decision" and r["listing_date"]})
    return settings.load_costs(years[0], years[-1]) if years else settings.load_costs(2023, 2023)


def settle_from_raw(ledger: Ledger, end: str, settled_at: datetime) -> int:
    """운영 진입점: 장부의 매수 종목 시세만 원본 KRX 자료(end 까지)에서 읽어 청산일이 지난 건을 정산한다."""
    rows = ledger.rows()
    buys = [r for r in rows if r["type"] == "decision" and r["action"] == "매수" and r["valid"]]
    if not buys:
        return 0
    start = min(r["listing_date"] for r in buys)
    index = BarIndex(list(iter_filtered_bars(start, end, {r["short_code"] for r in buys}))
                     + calendar_bars(start, end) + list(iter_index_bars(start, end)))
    return settle_due(ledger, index, costs_for(rows), settled_at)


if __name__ == "__main__":
    import sys

    import config
    cmd, end = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("settle", sys.argv[1] if len(sys.argv) > 1 else "")
    if cmd != "settle" or not end:
        raise SystemExit("사용법: python -m ops.paper_ledger settle YYYYMMDD   (장부: data/ledger/paper_a0.jsonl)")
    led = Ledger(config.DATA / "ledger" / "paper_a0.jsonl")
    print(f"[장부] 정산 {settle_from_raw(led, end, datetime.now().astimezone())}건 추가, 무결성 문제 {led.verify() or '없음'}")
