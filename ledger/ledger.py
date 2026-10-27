"""신호 장부(L7): 추가만 하는 JSONL. 각 행은 앞 행의 해시를 이어 붙여 사후 수정·중간 삭제를 탐지한다.

행 종류
  decision   : 판단 시점에 기록. 모의 운영에서 판단 시각(as_of)+5분 뒤에 기록된 행은 무효(valid=false)로 남긴다.
  settlement : 정산 뒤 같은 ledger_id 로 한 번만 추가한다.

보강
  - <장부>.head : 마지막 행의 해시와 행 수. 해시 체인만으로는 안 보이는 '마지막 행들의 삭제'를 verify() 가 대조한다.
    (head 와 장부를 함께 고치면 속일 수 있다 — 서로 다른 곳에 보관하면 더 단단해진다.)
  - <장부>.lock : 읽기-확인-쓰기 전체를 감싸는 잠금 파일. 동시에 두 곳이 쓰면 체인이 갈라지는 것을 막는다.
    이식성(Windows 작업 스케줄러)을 위해 fcntl 대신 O_EXCL 생성을 쓴다. 비정상 종료로 잠금이 남으면
    다른 프로세스가 없는지 확인한 뒤 .lock 파일을 직접 지운다.
"""
import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

GENESIS = "GENESIS"
LATE_AFTER = timedelta(minutes=5)
LOCK_POLL_SEC = 0.01


def _hash(prev: str, row: dict) -> str:
    body = json.dumps(row, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()


def decision_key(ipo_id: str, strategy: str, as_of: datetime) -> str:
    return hashlib.sha256(f"{ipo_id}|{strategy}|{as_of.isoformat()}".encode("utf-8")).hexdigest()[:16]


class Ledger:
    def __init__(self, path: Path, lock_timeout: float = 5.0):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.head_path = self.path.with_name(self.path.name + ".head")
        self.lock_timeout = lock_timeout

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"장부 잠금을 얻지 못함: {self.lock_path} — 다른 프로세스가 쓰는 중이거나 "
                                       f"비정상 종료로 남은 잠금이면 확인 후 직접 지울 것") from None
                time.sleep(LOCK_POLL_SEC)
        try:
            yield
        finally:
            os.remove(self.lock_path)

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _append(self, row: dict) -> None:
        """잠금을 잡은 상태에서만 부른다."""
        rows = self.rows()
        prev = rows[-1]["hash"] if rows else GENESIS
        row = {**row, "prev_hash": prev}
        row["hash"] = _hash(prev, {k: v for k, v in row.items() if k != "hash"})
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.head_path.write_text(json.dumps({"count": len(rows) + 1, "hash": row["hash"]}), encoding="utf-8")

    def append_decision(self, d, wallclock: datetime) -> str:
        ledger_id = decision_key(d.ipo_id, d.strategy, d.as_of)
        with self._locked():
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
        with self._locked():
            rows = self.rows()
            if not any(r["type"] == "decision" and r["ledger_id"] == ledger_id for r in rows):
                raise ValueError(f"알 수 없는 ledger_id: {ledger_id}")
            if any(r["type"] == "settlement" and r["ledger_id"] == ledger_id for r in rows):
                raise ValueError(f"이미 정산된 ledger_id: {ledger_id}")
            self._append({"type": "settlement", "ledger_id": ledger_id, **asdict(s), "settled_at": settled_at.isoformat()})

    def verify(self) -> list[str]:
        problems, prev, rows = [], GENESIS, self.rows()
        for n, row in enumerate(rows, start=1):
            body = {k: v for k, v in row.items() if k != "hash"}
            if row.get("prev_hash") != prev:
                problems.append(f"행 {n}: 이전 해시가 이어지지 않음 (행 삭제·순서 변경 의심)")
            if _hash(row.get("prev_hash", ""), body) != row.get("hash"):
                problems.append(f"행 {n}: 내용 해시 불일치 (사후 수정 의심)")
            prev = row.get("hash", "")
        problems += self._check_head(rows)
        return problems

    def _check_head(self, rows: list[dict]) -> list[str]:
        if not rows:
            return []
        if not self.head_path.exists():
            return ["head 기록(.head)이 없음 — 마지막 행 삭제 여부를 확인할 수 없다"]
        head = json.loads(self.head_path.read_text(encoding="utf-8"))
        if head.get("count") != len(rows) or head.get("hash") != rows[-1].get("hash"):
            return [f"마지막 행이 head 기록과 다름 (기록: {head.get('count')}행, 실제: {len(rows)}행) — 끝부분 삭제·교체 의심"]
        return []
