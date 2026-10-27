import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dart_list  # noqa: E402


def r(nm, name="가나다", no="20261001000001"):
    return {"report_nm": nm, "corp_name": name, "rcept_no": no, "rcept_dt": no[:8], "corp_code": "00000001"}


def test_report_kind_prefixes():
    assert dart_list.report_kind("증권신고서(지분증권)") == "최초"
    assert dart_list.report_kind("[기재정정]증권신고서(지분증권)") == "기재정정"
    assert dart_list.report_kind("[발행조건확정]증권신고서(지분증권)") == "발행조건확정"
    assert dart_list.report_kind("[첨부정정]증권신고서(지분증권)") == "첨부정정"
    assert dart_list.report_kind("[새접두사]증권신고서(지분증권)") == "기타:새접두사"


def test_equity_filter_excludes_debt_merger_and_spac():
    assert dart_list.is_equity_registration(r("[기재정정]증권신고서(지분증권)"))
    assert not dart_list.is_equity_registration(r("[발행조건확정]증권신고서(채무증권)"))
    assert not dart_list.is_equity_registration(r("증권신고서(합병)"))
    assert dart_list.is_spac(r("증권신고서(지분증권)", name="우리투자제1호기업인수목적"))
    assert dart_list.is_spac(r("증권신고서(지분증권)", name="OO스팩5호"))
    assert not dart_list.is_spac(r("증권신고서(지분증권)", name="케이엠에프"))


def _fake_fetch(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "RAW", tmp_path)
    calls = []

    def fake(bgn, end):
        calls.append((bgn, end))
        return [{"rcept_no": f"{end}000001", "report_nm": "증권신고서(지분증권)", "corp_name": "x",
                 "rcept_dt": end, "corp_code": "1"}]

    monkeypatch.setattr(dart_list, "_fetch_range", fake)
    return calls


def test_partial_past_month_is_not_cached_as_complete(monkeypatch, tmp_path):
    calls = _fake_fetch(monkeypatch, tmp_path)
    dart_list.equity_registrations("20250901", "20250915")          # 9월 중순까지만 요청
    calls.clear()
    got = dart_list.equity_registrations("20250901", "20250930")    # 이어서 9월 전체 요청
    assert calls == [("20250901", "20250930")]                      # 중순까지의 캐시를 재사용하면 안 된다
    assert got[-1]["rcept_dt"] == "20250930"


def test_complete_past_month_is_cached_and_not_refetched(monkeypatch, tmp_path):
    calls = _fake_fetch(monkeypatch, tmp_path)
    dart_list.equity_registrations("20250901", "20250930")
    dart_list.equity_registrations("20250901", "20250930")
    assert len(calls) == 1


def test_result_reports_are_grouped_by_corp_and_sorted_by_date(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "RAW", tmp_path)
    rows = [
        {"rcept_no": "20260108000730", "report_nm": "증권발행실적보고서", "corp_code": "1", "corp_name": "a", "rcept_dt": "20260108"},
        {"rcept_no": "20260101000001", "report_nm": "[기재정정]증권발행실적보고서", "corp_code": "1", "corp_name": "a", "rcept_dt": "20260101"},
        {"rcept_no": "20260102000002", "report_nm": "증권신고서(지분증권)", "corp_code": "1", "corp_name": "a", "rcept_dt": "20260102"},
        {"rcept_no": "20260103000003", "report_nm": "증권발행실적보고서", "corp_code": "2", "corp_name": "b", "rcept_dt": "20260103"},
    ]
    monkeypatch.setattr(dart_list, "_fetch_range", lambda bgn, end: rows)
    got = dart_list.result_reports("20260101", "20260131")
    assert [r["rcept_no"] for r in got["1"]] == ["20260101000001", "20260108000730"]
    assert [r["rcept_no"] for r in got["2"]] == ["20260103000003"]


def test_pick_result_report_takes_first_one_after_the_confirming_filing():
    reports = [{"rcept_no": "a", "rcept_dt": "20260101"}, {"rcept_no": "b", "rcept_dt": "20260108"},
               {"rcept_no": "c", "rcept_dt": "20260601"}]
    assert dart_list.pick_result_report(reports, "20260105")["rcept_no"] == "b"
    assert dart_list.pick_result_report(reports, "20260901") is None
    assert dart_list.pick_result_report([], "20260105") is None


def test_month_ranges_split_at_month_boundaries():
    got = list(dart_list.month_ranges("20230115", "20230305"))
    assert got == [("202301", "20230115", "20230131"), ("202302", "20230201", "20230228"),
                   ("202303", "20230301", "20230305")]
