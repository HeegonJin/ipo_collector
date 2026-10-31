"""모의 운영 화면 API (Ops): 일정 입력·장부 보기·작업 실행, HTTP 경로."""
import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.tradingcal import KST  # noqa: E402
from decide.runner import Decision  # noqa: E402
from lab.ops_api import Ops  # noqa: E402
from lab.server import make_server  # noqa: E402
from ledger.ledger import Ledger  # noqa: E402
from ops.paper_ledger import record_decisions  # noqa: E402
from test_lab_server import make_lab  # noqa: E402

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=KST)


def reg():
    return [{"corp_name": "새회사", "ipo_id": "I1", "is_ipo_candidate": "True", "list_dd": "", "first_rcept_dt": "20261001"}]


@pytest.fixture
def ops(tmp_path):
    calls = []
    runners = {"a0": lambda d: calls.append(("a0", d)) or [], "swing": lambda d, allow_stale=False: calls.append(("swing", d, allow_stale)) or [],
               "settle": lambda d: calls.append(("settle", d)) or {"settled": 0, "problems": [], "missing_bars": []}}
    o = Ops(tmp_path / "s.csv", tmp_path / "l.jsonl", registry=reg, runners=runners, now=lambda: NOW)
    o.calls = calls
    return o


def test_schedule_add_view_and_late_flag(ops):
    r = ops.schedule_add({"list_date": "20261116", "corp_name": "새회사", "stock_code": "0158s0", "offer_price": "10,000"})
    assert r["late"] is False and r["entry"]["stock_code"] == "0158S0"
    ops.schedule_add({"list_date": "20261109", "corp_name": "다른회사", "stock_code": "123456"})
    view = {e["corp_name"]: e for e in ops.schedule_view()["entries"]}
    assert view["새회사"]["ipo_id"] == "I1" and view["다른회사"]["ipo_id"] is None
    with pytest.raises(ValueError):
        ops.schedule_add({"list_date": "20261116", "corp_name": "새회사", "stock_code": "0158S0"})   # 중복


def test_ledger_view_joins_settlement_and_reports_integrity(ops, tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    as_of = datetime(2026, 11, 16, 15, 20, tzinfo=KST)
    d = Decision("I1", "A0", as_of, "매수", "D0_close", "D1_open", ("조건 없는 기준선",), "ABC", "20261116", 10000.0)
    record_decisions(led, [d], as_of)
    v = ops.ledger_view()
    assert v["problems"] == [] and v["items"][0]["settled"] is False and v["items"][0]["valid"] is True
    assert Ops(tmp_path / "s.csv", tmp_path / "none.jsonl", registry=reg).ledger_view()["items"] == []


def test_run_dispatches_and_validates(ops):
    ops.run({"cmd": "swing", "day": "20261116", "allow_stale": True})
    ops.run({"cmd": "a0", "day": "20261116"})
    assert ops.run({"cmd": "settle", "day": "20261116"})["result"]["settled"] == 0
    assert ops.calls == [("swing", "20261116", True), ("a0", "20261116"), ("settle", "20261116")]
    for bad in ({"cmd": "rm", "day": "20261116"}, {"cmd": "a0", "day": "2026-11-16"}, {"cmd": "a0"}):
        with pytest.raises(ValueError):
            ops.run(bad)


def test_http_routes(ops, tmp_path):
    srv = make_server(make_lab(tmp_path), 0, ops)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        assert post("/api/ops/schedule/add", {"list_date": "20261116", "corp_name": "새회사", "stock_code": "123456"})[0] == 200
        assert post("/api/ops/schedule/add", {"list_date": "20261115", "corp_name": "새회사", "stock_code": "123456"})[0] == 400   # 주말
        with urllib.request.urlopen(base + "/api/ops/schedule") as r:
            assert len(json.loads(r.read())["entries"]) == 1
        assert post("/api/ops/run", {"cmd": "settle", "day": "20261116"})[0] == 200
        ops.runners["a0"] = lambda d: (_ for _ in ()).throw(SystemExit("선행 조건 없음"))
        assert post("/api/ops/run", {"cmd": "a0", "day": "20261116"})[0] == 409
    finally:
        srv.shutdown()
