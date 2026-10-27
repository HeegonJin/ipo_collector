"""신호 장부(L7): 추가만 하는 JSONL. 각 행은 앞 행의 해시를 이어 붙여 사후 수정·중간 삭제를 탐지한다.

행 종류
  decision   : 판단 시점에 기록. 모의 운영에서 판단 시각(as_of)+5분 뒤에 기록된 행은 무효(valid=false)로 남긴다.
  settlement : 정산 뒤 같은 ledger_id 로 한 번만 추가한다.
한계: 해시 체인만으로는 '마지막 행들의 삭제'를 알 수 없다. 마지막 해시를 따로 보관하면 잡을 수 있다 (미구현).
"""
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

GENESIS = "GENESIS"
LATE_AFTER = timedelta(minutes=5)


def _hash(prev: str, row: dict) -> str:
    body = json.dumps(row, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()


def decision_key(ipo_id: str, strategy: str, as_of: datetime) -> str:
    return hashlib.sha256(f"{ipo_id}|{strategy}|{as_of.isoformat()}".encode("utf-8")).hexdigest()[:16]


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _append(self, row: dict) -> None:
        rows = self.rows()
        prev = rows[-1]["hash"] if rows else GENESIS
        row = {**row, "prev_hash": prev}
        row["hash"] = _hash(prev, {k: v for k, v in row.items() if k != "hash"})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def append_decision(self, d, wallclock: datetime) -> str:
        ledger_id = decision_key(d.ipo_id, d.strategy, d.as_of)
        if any(r["type"] == "decision" and r["ledger_id"] == ledger_id for r in self.rows()):
            return ledger_id
        late = wallclock > d.as_of + LATE_AFTER
        fields = asdict(d)
        fields["as_of"] = d.as_of.isoformat()
        fields["reasons"] = list(d.reasons)
        self._append({"type": "decision", "ledger_id": ledger_id, **fields,
                      "decided_at_wallclock": wallclock.isoformat(), "valid": not late,
                      "invalid_reason": "판단 시각(as_of) + 5분 초과 기록" if late else None})
        return ledger_id

    def append_settlement(self, ledger_id: str, s, settled_at: datetime) -> None:
        rows = self.rows()
        if not any(r["type"] == "decision" and r["ledger_id"] == ledger_id for r in rows):
            raise ValueError(f"알 수 없는 ledger_id: {ledger_id}")
        if any(r["type"] == "settlement" and r["ledger_id"] == ledger_id for r in rows):
            raise ValueError(f"이미 정산된 ledger_id: {ledger_id}")
        self._append({"type": "settlement", "ledger_id": ledger_id, **asdict(s), "settled_at": settled_at.isoformat()})

    def verify(self) -> list[str]:
        problems, prev = [], GENESIS
        for n, row in enumerate(self.rows(), start=1):
            body = {k: v for k, v in row.items() if k != "hash"}
            if row.get("prev_hash") != prev:
                problems.append(f"행 {n}: 이전 해시가 이어지지 않음 (행 삭제·순서 변경 의심)")
            if _hash(row.get("prev_hash", ""), body) != row.get("hash"):
                problems.append(f"행 {n}: 내용 해시 불일치 (사후 수정 의심)")
            prev = row.get("hash", "")
        return problems
