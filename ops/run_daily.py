"""일일 자동 실행 진입점 (macOS launchd 가 부른다 — ops/launchd.py). 사람이 직접 불러도 된다.

  python -m ops.run_daily morning   [YYYYMMDD]   # 08:30 — 전 거래일 시세 수집 → 전략 B·C 판단 → 정산
  python -m ops.run_daily afternoon [YYYYMMDD]   # 15:20 — 오늘 상장하는 수기 일정 종목 A0 판단

전진 검증 시작일(config/splits_v1.yaml 의 forward.start) 전에는 '연습 모드': 판단은 하지만 실제 장부(data/ledger)에는 쓰지 않고
임시 장부에 쓴다. 그 뒤에는 실제 장부에 기록한다. 결과는 data/_meta/daily_job.log 에 시각과 함께 남는다 (실패도 남긴다).
판단 시각 +5분 뒤에 기록하면 그 행은 장부에서 무효가 되므로 시각에 맞춰 실행해야 한다.
"""
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path

import config
import krx_api
from core import settings
from core.tradingcal import KST
from ops import daily_job, report

LOG = config.META / "daily_job.log"
FETCH_TRIES, FETCH_WAIT_SEC = 4, 60      # KRX 일별 자료가 아직 안 올라왔으면 1분씩 기다린다 (08:30 → 08:34 까지)


def forward_start() -> str:
    return str(settings.load_splits()["forward"]["start"]).replace("-", "")


def log(text: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now(KST):%Y-%m-%d %H:%M:%S}] {text}\n")


def _practice_ledger(practice: bool):
    return Path(tempfile.mkdtemp(prefix="ipo_practice_")) / "ledger.jsonl" if practice else None


def notify(title: str, message: str) -> None:
    """macOS 알림 센터. 실패해도 본 작업에는 영향이 없다 (다른 OS 에서는 조용히 건너뜀)."""
    if sys.platform != "darwin":
        return
    text = message.replace("\\", " ").replace('"', "'")[:200]
    subprocess.run(["osascript", "-e", f'display notification "{text}" with title "{title}"'], capture_output=True)


def finish(kind: str, day: str, ledger, body: str) -> None:
    """로그 + 일일 리포트(results/daily) + 문제가 있으면 알림."""
    path = report.write(day, ledger_path=ledger)
    problems = [f"{a}: {c}" for a, st, c in report.health(day, ledger_path=ledger) if st == "오류"]
    late = "[경고]" in body
    log(f"report {path}")
    if problems or late:
        notify(f"IPO 에이전트 {kind} 경고", "; ".join(problems) or "판단이 늦게 기록되어 무효 처리됨")
    elif "매수" in body:
        notify(f"IPO 에이전트 {kind}", "새 매수 판단이 있습니다. 리포트를 확인하세요.")


def morning(day: str, practice: bool) -> None:
    prev = daily_job.previous_weekday(day)
    for attempt in range(FETCH_TRIES):
        krx_api.collect(config.BUFFER_START, prev)
        if (config.RAW / "krx" / "ksq_daily" / f"{prev}.json").exists():
            break
        if attempt < FETCH_TRIES - 1:
            time.sleep(FETCH_WAIT_SEC)
    ledger = _practice_ledger(practice)
    buf = StringIO()
    try:
        with redirect_stdout(buf):
            daily_job.print_report(daily_job.run_swing(day, ledger_path=ledger))
    except SystemExit as e:                        # 전 거래일 자료가 없다 (휴장일이거나 아직 미공개)
        buf.write(f"B·C 판단 건너뜀: {e}\n")
    log(f"morning {day} {'(연습, 장부 미기록)' if practice else ''}\n{buf.getvalue().rstrip()}")
    if not practice:
        res = daily_job.run_settle(prev)
        log(f"settle {prev}: 정산 {res['settled']}건, 무결성 {res['problems'] or '정상'}, 시세 없음 {res['missing_bars'] or '없음'}")
    finish("아침", day, ledger, buf.getvalue())


def afternoon(day: str, practice: bool) -> None:
    buf, ledger = StringIO(), _practice_ledger(practice)
    with redirect_stdout(buf):
        daily_job.print_report(daily_job.run_a0(day, ledger_path=ledger))
    log(f"afternoon {day} {'(연습, 장부 미기록)' if practice else ''}\n{buf.getvalue().rstrip()}")
    finish("오후", day, ledger, buf.getvalue())


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] not in ("morning", "afternoon"):
        print("사용: python -m ops.run_daily {morning|afternoon} [YYYYMMDD]")
        return 2
    day = argv[1] if len(argv) > 1 else datetime.now(KST).strftime("%Y%m%d")
    datetime.strptime(day, "%Y%m%d")
    if datetime.strptime(day, "%Y%m%d").weekday() >= 5:
        log(f"{argv[0]} {day}: 주말이라 건너뜀")
        return 0
    practice = day < forward_start()
    try:
        (morning if argv[0] == "morning" else afternoon)(day, practice)
    except Exception:                              # 자동 실행이 조용히 죽지 않게 사유를 남긴다
        log(f"{argv[0]} {day} 실패:\n{traceback.format_exc()}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
