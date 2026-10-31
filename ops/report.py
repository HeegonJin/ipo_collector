"""L7 출력: 일일 리포트(마크다운)와 데이터 건강판. 판단을 새로 하지 않고 장부·캐시를 읽어 요약만 한다.

  python -m ops.report [YYYYMMDD]    # results/daily/<날짜>.md 에 쓰고 경로를 출력
건강판은 '무엇이 오래됐나/비었나'만 보여 준다 (수집 최신일, 장부 무결성, 일정 입력, DART 미연결, KRX 공개 시각 측정 건수).
"""
import calendar
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import config
from core.tradingcal import KST
from ledger.ledger import Ledger
from ops import daily_job, schedule

OUT_DIR = config.ROOT / "results" / "daily"
STALE_DAYS = 4          # 최신 KRX 일별 자료가 이보다 오래되면 경고 (주말·휴장 감안)


def latest_krx_day() -> str | None:
    d = config.RAW / "krx" / "ksq_daily"
    days = sorted(p.stem for p in d.glob("*.json")) if d.exists() else []
    return days[-1] if days else None


def health(today: str, ledger_path=None, schedule_path=None) -> list[tuple[str, str, str]]:
    """(항목, 상태 '정상'|'주의'|'오류', 설명)"""
    out = []
    last = latest_krx_day()
    if last is None:
        out.append(("KRX 일별 자료", "오류", "수집된 자료가 없습니다"))
    else:
        gap = (datetime.strptime(today, "%Y%m%d") - datetime.strptime(last, "%Y%m%d")).days
        out.append(("KRX 일별 자료", "정상" if gap <= STALE_DAYS else "주의", f"최신 {last} (오늘보다 {gap}일 전)"))
    led = Ledger(ledger_path or daily_job.LEDGER_PATH)
    problems = led.verify()
    out.append(("장부 무결성", "정상" if not problems else "오류", f"{len(led.rows())}행" + ("" if not problems else " — " + "; ".join(problems[:3]))))
    late = [r for r in led.rows() if r["type"] == "decision" and not r["valid"]]
    out.append(("늦게 기록된 판단", "정상" if not late else "주의", f"{len(late)}건 (판단 시각 +5분 초과, 무효)"))
    entries = schedule.load(Path(schedule_path) if schedule_path else schedule.PATH)
    upcoming = [e for e in entries if e.list_date >= today]
    out.append(("상장 일정(수기)", "정상" if upcoming else "주의", f"오늘 이후 {len(upcoming)}건" + ("" if upcoming else " — 입력하지 않으면 A0 판단이 비어 있습니다")))
    gaps = config.MART / "universe_gaps.csv"
    if gaps.exists():
        with open(gaps, encoding="utf-8-sig", newline="") as f:
            n = sum(1 for _ in csv.DictReader(f))
        out.append(("유니버스 누락 후보", "정상" if n == 0 else "주의", f"{n}건 (universe_gaps.csv)"))
    pub = config.META / "krx_publish_log.csv"
    out.append(("KRX 공개 시각 측정", "정상" if pub.exists() else "주의",
                f"{max(sum(1 for _ in open(pub, encoding='utf-8')) - 1, 0)}건 기록" if pub.exists() else "아직 기록 없음 (11-03 이후 측정 시작)"))
    return out


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, mo = d.year + m // 12, m % 12 + 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def unlock_calendar(day: str, horizon_days: int = 30, demand_path: Path | None = None,
                    registry_path: Path | None = None) -> list[dict]:
    """공시 문장에서 읽은 보호예수 해제 일정(상장일 + N개월)이 day ~ day+horizon 안에 오는 종목.
    해제일은 거래일이 아니면 다음 거래일로 밀릴 수 있어 '이후 첫 영업일'이 아닌 달력일 그대로 보여 준다.
    문장에서 일부만 읽힌 종목은 coverage 로 표시한다 (표가 불완전하면 빠진 해제가 있을 수 있다)."""
    demand_path = demand_path or config.MART / "dart_demand.csv"
    registry_path = registry_path or config.MART / "dart_ipo_registry.csv"
    if not demand_path.exists() or not registry_path.exists():
        return []
    with open(registry_path, encoding="utf-8-sig", newline="") as f:
        listed = {r["ipo_id"]: r["list_dd"] for r in csv.DictReader(f) if r["list_dd"]}
    start = datetime.strptime(day, "%Y%m%d").date()
    end = start + timedelta(days=horizon_days)
    out = []
    with open(demand_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if not r.get("lockups") or r["ipo_id"] not in listed:
                continue
            ld = datetime.strptime(listed[r["ipo_id"]], "%Y%m%d").date()
            for months, shares in json.loads(r["lockups"]).items():
                when = add_months(ld, int(months))
                if start <= when <= end:
                    out.append({"corp_name": r["corp_name"], "date": when.isoformat(), "months": int(months),
                                "shares": shares, "coverage": r.get("lockup_coverage") or "알 수 없음"})
    return sorted(out, key=lambda x: (x["date"], x["corp_name"]))


def render(day: str, ledger_path=None, schedule_path=None) -> str:
    led = Ledger(ledger_path or daily_job.LEDGER_PATH)
    rows = led.rows()
    iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    decisions = [r for r in rows if r["type"] == "decision" and r["as_of"][:10] == iso]
    settled = {r["ledger_id"]: r for r in rows if r["type"] == "settlement" and r["settled_at"][:10] == iso}
    names = {r["ipo_id"]: r.get("corp_name", r["ipo_id"]) for r in schedule.registry_rows()} if (config.MART / "dart_ipo_registry.csv").exists() else {}
    lines = [f"# 일일 리포트 {iso}", "", "모의 매매 기록입니다. 투자 조언이 아닙니다. 시세: KRX 통계정보.", "", "## 오늘의 판단", ""]
    if decisions:
        lines += ["| 종목 | 전략 | 행동 | 비중 | 유효 | 사유 |", "|---|---|---|---|---|---|"]
        for r in decisions:
            w = f"{r['weight']:.1%}" if r.get("weight") else "-"
            lines.append(f"| {names.get(r['ipo_id'], r['ipo_id'])} | {r['strategy']} | {r['action']} | {w} | {'예' if r['valid'] else '무효'} | {'; '.join(r['reasons'])} |")
    else:
        lines.append("판단한 종목이 없습니다.")
    lines += ["", "## 오늘 정산", ""]
    if settled:
        lines += ["| 종목 | 전략 | 순수익률 | 종료 유형 |", "|---|---|---|---|"]
        dec_by_id = {r["ledger_id"]: r for r in rows if r["type"] == "decision"}
        for lid, s in settled.items():
            d = dec_by_id[lid]
            nr = f"{s['net_ret']:.2%}" if s["net_ret"] is not None else "계산 불가"
            lines.append(f"| {names.get(d['ipo_id'], d['ipo_id'])} | {d['strategy']} | {nr} | {s['exit_kind']} |")
    else:
        lines.append("정산한 건이 없습니다.")
    unlocks = unlock_calendar(day)
    lines += ["", "## 보호예수 해제 예정 (앞으로 30일)", ""]
    if unlocks:
        lines += ["공시 문장에서 읽은 일정만 포함합니다. 읽히지 않은 해제는 빠져 있을 수 있습니다.", "",
                  "| 해제일 | 종목 | 상장 후 | 주식 수 | 파싱 커버리지 |", "|---|---|---|---|---|"]
        for u in unlocks:
            cov = f"{float(u['coverage']):.0%}" if u["coverage"].replace(".", "", 1).isdigit() else u["coverage"]
            lines.append(f"| {u['date']} | {u['corp_name']} | {u['months']}개월 | {u['shares']:,} | {cov} |")
    else:
        lines.append("읽힌 해제 일정 중 해당 기간에 오는 것이 없습니다.")
    lines += ["", "## 데이터 건강판", "", "| 항목 | 상태 | 설명 |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in health(day, ledger_path, schedule_path)]
    return "\n".join(lines) + "\n"


def write(day: str, ledger_path=None, schedule_path=None, out_dir: Path | None = None) -> Path:
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.md"
    path.write_text(render(day, ledger_path, schedule_path), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write(sys.argv[1] if len(sys.argv) > 1 else datetime.now(KST).strftime("%Y%m%d")))
