"""macOS launchd 에 일일 자동 실행을 등록한다 (사용자 영역 LaunchAgents, 관리자 권한 불필요).

  python -m ops.launchd install     # 평일 08:30 (morning), 15:20 (afternoon) 등록
  python -m ops.launchd status      # 등록 여부
  python -m ops.launchd uninstall   # 해제

맥이 잠들어 있으면 깨어난 뒤에 실행돼 판단 시각 +5분을 넘기고, 그 행은 장부에서 무효로 남는다(로그에 경고). 절전을 막으려면 시스템 설정에서 직접 조정한다.
전진 검증 시작일 전에는 연습 모드로만 돈다 (ops/run_daily.py).
"""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = Path.home() / "Library" / "LaunchAgents"
JOBS = {"morning": (8, 30), "afternoon": (15, 20)}
LABEL = "com.ipo-agent.{}"


def plist_for(job: str, root: Path = ROOT, python: Path | None = None) -> dict:
    hour, minute = JOBS[job]
    python = python or root / ".venv" / "bin" / "python"
    return {
        "Label": LABEL.format(job),
        "ProgramArguments": [str(python), "-m", "ops.run_daily", job],
        "WorkingDirectory": str(root),
        "StartCalendarInterval": [{"Weekday": wd, "Hour": hour, "Minute": minute} for wd in range(1, 6)],
        "StandardOutPath": str(root / "data" / "_meta" / f"launchd_{job}.out.log"),
        "StandardErrorPath": str(root / "data" / "_meta" / f"launchd_{job}.err.log"),
    }


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install() -> None:
    AGENTS.mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "_meta").mkdir(parents=True, exist_ok=True)
    for job in JOBS:
        path = AGENTS / f"{LABEL.format(job)}.plist"
        subprocess.run(["launchctl", "bootout", _domain(), str(path)], capture_output=True)   # 이미 있으면 갱신
        path.write_bytes(plistlib.dumps(plist_for(job)))
        subprocess.run(["launchctl", "bootstrap", _domain(), str(path)], check=True)
        print(f"등록: {path}")


def uninstall() -> None:
    for job in JOBS:
        path = AGENTS / f"{LABEL.format(job)}.plist"
        subprocess.run(["launchctl", "bootout", _domain(), str(path)], capture_output=True)
        path.unlink(missing_ok=True)
        print(f"해제: {LABEL.format(job)}")


def status() -> None:
    for job in JOBS:
        r = subprocess.run(["launchctl", "print", f"{_domain()}/{LABEL.format(job)}"], capture_output=True, text=True)
        print(f"{LABEL.format(job)}: {'등록됨' if r.returncode == 0 else '등록 안 됨'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"install": install, "uninstall": uninstall, "status": status}.get(cmd, lambda: print(__doc__))()
