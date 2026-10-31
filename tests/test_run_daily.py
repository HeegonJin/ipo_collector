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


def test_report_and_health_on_an_empty_ledger(tmp_path, monkeypatch):
    from ops import report
    monkeypatch.setattr(report.config, "RAW", tmp_path / "raw")
    monkeypatch.setattr(report.config, "META", tmp_path / "meta")
    monkeypatch.setattr(report.config, "MART", tmp_path / "mart")
    text = report.render("20261116", ledger_path=tmp_path / "l.jsonl", schedule_path=tmp_path / "s.csv")
    assert "판단한 종목이 없습니다" in text and "KRX 일별 자료 | 오류" in text and "상장 일정(수기) | 주의" in text


def test_config_hash_is_recorded_on_decisions_and_changes_with_config(tmp_path):
    import shutil
    from core import settings
    shutil.copytree(settings.CONFIG_DIR, tmp_path / "c")
    a = settings.config_hash(tmp_path / "c")
    (tmp_path / "c" / "risk_v1.yaml").write_text((tmp_path / "c" / "risk_v1.yaml").read_text() + "\n# x\n")
    assert settings.config_hash(tmp_path / "c") != a and settings.config_hash() == settings.config_hash()


def test_unlock_calendar_adds_months_to_the_listing_day(tmp_path):
    from datetime import date
    from ops import report
    assert report.add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)
    (tmp_path / "reg.csv").write_text("ipo_id,list_dd\nA,20260515\nB,\n", encoding="utf-8")
    (tmp_path / "dem.csv").write_text('ipo_id,corp_name,lockups,lockup_coverage\nA,가,"{""6"": 1000, ""12"": 5}",0.5\nB,나,"{""1"": 3}",\n', encoding="utf-8")
    got = report.unlock_calendar("20261101", demand_path=tmp_path / "dem.csv", registry_path=tmp_path / "reg.csv")
    assert [(g["corp_name"], g["date"], g["shares"]) for g in got] == [("가", "2026-11-15", 1000)]
