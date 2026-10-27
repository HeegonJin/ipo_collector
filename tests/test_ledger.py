import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.tradingcal import KST  # noqa: E402
from decide.runner import Decision  # noqa: E402
from evaluate.outcomes import Settlement  # noqa: E402
from ledger.ledger import Ledger  # noqa: E402

AS_OF = datetime(2026, 10, 23, 15, 20, tzinfo=KST)


def decision(ipo_id="00123456_20261001000123", as_of=AS_OF, action="매수"):
    return Decision(ipo_id, "A0", as_of, action, "D0_close", "D1_open", ("조건 없는 기준선",),
                    "0158S0", "20261023", 18500.0)


def settlement(ipo_id="00123456_20261001000123", net=0.05):
    return Settlement(ipo_id, "A0", 25000.0, 26000.0, 0.04, net, False, 0.01, "확인")


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.jsonl")


def test_chain_verifies_after_appends(ledger):
    a = ledger.append_decision(decision("A"), wallclock=AS_OF + timedelta(seconds=30))
    ledger.append_decision(decision("B"), wallclock=AS_OF + timedelta(seconds=40))
    ledger.append_settlement(a, settlement("A"), settled_at=AS_OF + timedelta(days=1))
    assert ledger.verify() == []
    assert len(ledger.rows()) == 3


def test_editing_a_written_row_is_detected(ledger, tmp_path):
    ledger.append_decision(decision("A"), wallclock=AS_OF)
    ledger.append_decision(decision("B"), wallclock=AS_OF)
    lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0]); row["action"] = "관망"
    lines[0] = json.dumps(row, ensure_ascii=False)
    (tmp_path / "ledger.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    problems = Ledger(tmp_path / "ledger.jsonl").verify()
    assert problems and "1" in problems[0]


def test_deleting_a_middle_row_is_detected(ledger, tmp_path):
    for x in "ABC":
        ledger.append_decision(decision(x), wallclock=AS_OF)
    lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    (tmp_path / "ledger.jsonl").write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert Ledger(tmp_path / "ledger.jsonl").verify()


def test_late_decision_is_recorded_but_marked_invalid(ledger):
    ok = ledger.append_decision(decision("A"), wallclock=AS_OF + timedelta(minutes=5))
    late = ledger.append_decision(decision("B"), wallclock=AS_OF + timedelta(minutes=5, seconds=1))
    by = {r["ledger_id"]: r for r in ledger.rows()}
    assert by[ok]["valid"] is True
    assert by[late]["valid"] is False and "5분" in by[late]["invalid_reason"]


def test_same_decision_twice_is_one_row(ledger):
    a = ledger.append_decision(decision("A"), wallclock=AS_OF)
    b = ledger.append_decision(decision("A"), wallclock=AS_OF + timedelta(minutes=1))
    assert a == b and len(ledger.rows()) == 1


def test_settlement_needs_known_decision_and_only_once(ledger):
    with pytest.raises(ValueError):
        ledger.append_settlement("nope", settlement(), settled_at=AS_OF)
    a = ledger.append_decision(decision("A"), wallclock=AS_OF)
    ledger.append_settlement(a, settlement("A"), settled_at=AS_OF + timedelta(days=1))
    with pytest.raises(ValueError):
        ledger.append_settlement(a, settlement("A"), settled_at=AS_OF + timedelta(days=2))


def test_new_instance_continues_the_same_chain(ledger, tmp_path):
    ledger.append_decision(decision("A"), wallclock=AS_OF)
    again = Ledger(tmp_path / "ledger.jsonl")
    again.append_decision(decision("B"), wallclock=AS_OF)
    assert again.verify() == [] and len(again.rows()) == 2


def test_deleting_the_last_rows_is_detected_via_the_head_record(ledger, tmp_path):
    for x in "ABC":
        ledger.append_decision(decision(x), wallclock=AS_OF)
    p = tmp_path / "ledger.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines()
    p.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")        # 마지막 행 삭제: 해시 체인만으로는 안 보인다
    problems = Ledger(p).verify()
    assert problems and "마지막" in problems[0]


def test_head_record_follows_every_append(ledger, tmp_path):
    ledger.append_decision(decision("A"), wallclock=AS_OF)
    again = Ledger(tmp_path / "ledger.jsonl")
    again.append_decision(decision("B"), wallclock=AS_OF)
    assert again.verify() == []


def test_a_held_lock_blocks_appends_instead_of_forking_the_chain(tmp_path):
    p = tmp_path / "ledger.jsonl"
    (tmp_path / "ledger.jsonl.lock").write_text("held", encoding="utf-8")   # 다른 프로세스가 쓰는 중
    with pytest.raises(TimeoutError):
        Ledger(p, lock_timeout=0.2).append_decision(decision("A"), wallclock=AS_OF)
    assert not p.exists()


def test_lock_file_is_released_after_an_append(ledger, tmp_path):
    ledger.append_decision(decision("A"), wallclock=AS_OF)
    assert not (tmp_path / "ledger.jsonl.lock").exists()


def test_concurrent_writers_keep_one_valid_chain(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    p = tmp_path / "ledger.jsonl"
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda i: Ledger(p).append_decision(decision(f"I{i}"), wallclock=AS_OF), range(24)))
    led = Ledger(p)
    assert len(led.rows()) == 24 and led.verify() == []


def test_missing_values_are_stored_as_null_not_zero(ledger):
    a = ledger.append_decision(decision("A"), wallclock=AS_OF)
    s = Settlement("A", "A0", None, None, None, None, None, None, "계산 불가")
    ledger.append_settlement(a, s, settled_at=AS_OF + timedelta(days=1))
    row = ledger.rows()[-1]
    assert row["net_ret"] is None and row["buy_at_limit_up"] is None and row["net_ret_status"] == "계산 불가"
