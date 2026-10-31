"""일일 자동 실행: 연습/실전 구분, 주말 건너뜀, launchd 설정 내용 (실제 등록은 하지 않는다)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops import launchd, run_daily  # noqa: E402


def test_practice_mode_until_the_forward_start():
    assert run_daily.forward_start() == "20261116"
    assert "20261113" < run_daily.forward_start() <= "20261116"


def test_weekend_is_skipped_and_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(run_daily, "LOG", tmp_path / "x.log")
    assert run_daily.main(["morning", "20261114"]) == 0           # 토요일
    assert "주말" in (tmp_path / "x.log").read_text(encoding="utf-8")


def test_failures_are_logged_not_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(run_daily, "LOG", tmp_path / "x.log")
    monkeypatch.setattr(run_daily, "morning", lambda day, practice: (_ for _ in ()).throw(RuntimeError("boom")))
    assert run_daily.main(["morning", "20261116"]) == 1
    assert "boom" in (tmp_path / "x.log").read_text(encoding="utf-8")


def test_launchd_plist_runs_weekdays_at_the_decision_times(tmp_path):
    m = launchd.plist_for("morning", tmp_path, Path("/py"))
    a = launchd.plist_for("afternoon", tmp_path, Path("/py"))
    assert m["ProgramArguments"] == ["/py", "-m", "ops.run_daily", "morning"] and m["WorkingDirectory"] == str(tmp_path)
    assert [(d["Weekday"], d["Hour"], d["Minute"]) for d in m["StartCalendarInterval"]] == [(w, 8, 30) for w in range(1, 6)]
    assert {(d["Hour"], d["Minute"]) for d in a["StartCalendarInterval"]} == {(15, 20)}
