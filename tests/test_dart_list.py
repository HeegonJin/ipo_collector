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


def test_month_ranges_split_at_month_boundaries():
    got = list(dart_list.month_ranges("20230115", "20230305"))
    assert got == [("202301", "20230115", "20230131"), ("202302", "20230201", "20230228"),
                   ("202303", "20230301", "20230305")]
