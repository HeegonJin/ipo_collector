"""모의 운영 화면용 API: 상장 일정 수기 입력, 장부 보기, 일일 판단 작업 실행.

실행(run)은 ops.daily_job 을 그대로 부른다. 판단 시각(A0 15:20, B·C 08:30) +5분을 넘기면 장부에는 무효로 남으므로
화면에서도 시각 경고를 함께 돌려준다. 장부는 추가만 되고 지울 수 없다.
"""
from datetime import datetime

from core.tradingcal import KST
from ledger.ledger import Ledger
from ops import daily_job, schedule
from ops.paper_ledger import LEDGER_PATH

COMMANDS = ("a0", "swing", "settle")


def _day(value) -> str:
    if not isinstance(value, str):
        raise ValueError("날짜는 YYYYMMDD 문자열이어야 함")
    datetime.strptime(value, "%Y%m%d")
    return value


class Ops:
    def __init__(self, schedule_path=None, ledger_path=None, registry=None, runners=None, now=None):
        self.schedule_path = schedule_path or schedule.PATH
        self.ledger_path = ledger_path or LEDGER_PATH
        self._registry = registry or schedule.registry_rows
        self.runners = runners or {"a0": daily_job.run_a0, "swing": daily_job.run_swing, "settle": daily_job.run_settle}
        self._now = now or (lambda: datetime.now(KST))

    def schedule_view(self) -> dict:
        try:
            reg, reg_error = self._registry(), ""
        except OSError as e:
            reg, reg_error = [], f"DART 레지스트리를 못 읽음: {e}"
        out = []
        for e in sorted(schedule.load(self.schedule_path), key=lambda x: (x.list_date, x.stock_code), reverse=True):
            row = schedule.match_registry(e, reg) if reg else None
            out.append({"list_date": e.list_date, "corp_name": e.corp_name, "stock_code": e.stock_code,
                        "offer_price": e.offer_price, "entered_at": e.entered_at.isoformat(),
                        "ipo_id": row["ipo_id"] if row else None})
        return {"entries": out, "registry_error": reg_error}

    def schedule_add(self, body: dict) -> dict:
        e = schedule.add(self.schedule_path, _day(body.get("list_date")), str(body.get("corp_name", "")),
                         str(body.get("stock_code", "")), body.get("offer_price") or None, self._now())
        late = e.entered_at > datetime.strptime(e.list_date, "%Y%m%d").replace(hour=15, minute=20, tzinfo=KST)
        return {"entry": {"list_date": e.list_date, "corp_name": e.corp_name, "stock_code": e.stock_code},
                "late": late}

    def ledger_view(self) -> dict:
        led = Ledger(self.ledger_path)
        rows = led.rows()
        settled = {r["ledger_id"]: r for r in rows if r["type"] == "settlement"}
        items = []
        for r in rows:
            if r["type"] != "decision":
                continue
            s = settled.get(r["ledger_id"])
            items.append({"as_of": r["as_of"], "strategy": r["strategy"], "ipo_id": r["ipo_id"], "short_code": r["short_code"],
                          "action": r["action"], "reasons": r["reasons"], "valid": r["valid"], "invalid_reason": r["invalid_reason"],
                          "settled": s is not None, "net_ret": s.get("net_ret") if s else None,
                          "exit_kind": s.get("exit_kind") if s else None, "exit_reason": s.get("exit_reason") if s else None,
                          "exit_date": s.get("exit_date") if s else None})
        items.reverse()
        return {"items": items, "problems": led.verify(), "rows": len(rows)}

    def run(self, body: dict) -> dict:
        cmd, day = body.get("cmd"), _day(body.get("day"))
        if cmd not in COMMANDS:
            raise ValueError(f"알 수 없는 작업: {cmd!r}")
        if cmd == "settle":
            return {"cmd": cmd, "result": self.runners["settle"](day)}
        report = self.runners[cmd](day, allow_stale=True) if cmd == "swing" and body.get("allow_stale") else self.runners[cmd](day)
        return {"cmd": cmd, "report": report}
