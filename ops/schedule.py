"""상장 일정 수기 입력 (data/_meta/listing_schedule.csv).

상장 예정일을 자동으로 얻을 무료 출처가 없어서(KIND 는 방화벽, DART·예탁결제원 API 에는 예정일이 없음) 사람이 직접 적는다.
일일 판단 작업(ops.daily_job)이 이 파일을 읽는다. 입력한 시각(entered_at)이 그 값의 available_at 이라서,
상장일 15:20 판단 시각보다 늦게 적으면 그 종목은 판단에 쓰이지 않는다 (PIT).

  python -m ops.schedule add 20261116 회사이름 0158S0 [공모가]    # 한 줄 추가 (입력 시각은 지금)
  python -m ops.schedule list                                      # 입력된 일정
  python -m ops.schedule check 20261116                            # 그날 상장 예정 종목이 DART 레지스트리와 연결되는지

열: list_date(YYYYMMDD), corp_name(DART 회사명과 같게), stock_code(6자리 단축코드, 영문 섞일 수 있음), offer_price(선택), entered_at.
"""
import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import config
from core.schema import Fact, Phase, SourceType, Status
from core.tradingcal import KST, dart_available_at

PATH = config.META / "listing_schedule.csv"
COLUMNS = ["list_date", "corp_name", "stock_code", "offer_price", "entered_at"]
CODE_RE = re.compile(r"^[0-9A-Z]{6}$")


@dataclass(frozen=True)
class Entry:
    list_date: str
    corp_name: str
    stock_code: str
    offer_price: float | None
    entered_at: datetime


def parse_entry(row: dict) -> Entry:
    try:
        d = datetime.strptime(row["list_date"], "%Y%m%d")
    except (KeyError, ValueError):
        raise ValueError(f"list_date 는 YYYYMMDD 여야 함: {row.get('list_date')!r}") from None
    if d.weekday() >= 5:
        raise ValueError(f"주말은 상장일이 될 수 없음: {row['list_date']}")
    name = (row.get("corp_name") or "").strip()
    if not name:
        raise ValueError("corp_name 이 비어 있음")
    code = (row.get("stock_code") or "").strip()
    if not CODE_RE.match(code):
        raise ValueError(f"stock_code 는 6자리 영대문자·숫자여야 함: {code!r}")
    raw_price = (row.get("offer_price") or "").strip().replace(",", "")
    price = None
    if raw_price:
        price = float(raw_price)
        if price <= 0:
            raise ValueError(f"offer_price 는 양수여야 함: {raw_price}")
    try:
        at = datetime.fromisoformat(row["entered_at"])
    except (KeyError, ValueError):
        raise ValueError(f"entered_at 은 ISO 시각이어야 함: {row.get('entered_at')!r}") from None
    if at.tzinfo is None:
        raise ValueError("entered_at 에는 타임존이 필요함")
    return Entry(row["list_date"], name, code, price, at)


def load(path: Path = PATH) -> list[Entry]:
    """파일이 없으면 빈 목록. 잘못된 줄은 줄 번호와 함께 예외 (조용히 건너뛰지 않는다)."""
    if not Path(path).exists():
        return []
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            try:
                out.append(parse_entry(row))
            except ValueError as e:
                raise ValueError(f"{path} {n}번째 줄: {e}") from None
    return out


def add(path: Path, list_date: str, corp_name: str, stock_code: str, offer_price: str | float | None = None,
        now: datetime | None = None) -> Entry:
    now = now or datetime.now(KST)
    entry = parse_entry({"list_date": list_date, "corp_name": corp_name, "stock_code": stock_code.upper(),
                         "offer_price": "" if offer_price is None else str(offer_price), "entered_at": now.isoformat()})
    path = Path(path)
    if any(e.list_date == entry.list_date and e.stock_code == entry.stock_code for e in load(path)):
        raise ValueError(f"이미 입력됨: {entry.list_date} {entry.stock_code}")
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(COLUMNS)
        w.writerow([entry.list_date, entry.corp_name, entry.stock_code,
                    "" if entry.offer_price is None else f"{entry.offer_price:g}", entry.entered_at.isoformat()])
    return entry


def match_registry(entry: Entry, registry_rows: list[dict]) -> dict | None:
    """DART 레지스트리에서 같은 회사명의 아직 상장 전이거나 그날 상장한 신규상장 후보 중 가장 최근 신고서."""
    cands = [r for r in registry_rows if r["corp_name"] == entry.corp_name and r["is_ipo_candidate"] == "True"
             and r["list_dd"] in ("", entry.list_date)]
    return max(cands, key=lambda r: r["first_rcept_dt"]) if cands else None


def facts_for(entry: Entry, ipo_id: str, registry_row: dict) -> list[Fact]:
    """일정 한 줄 → Fact. 상장일·종목코드는 입력 시각부터, 공모가는 입력값(있으면) 아니면 레지스트리의 확정값."""
    common = dict(ipo_id=ipo_id, information_phase=Phase.PRE_LISTING)
    out = [Fact(var="listing_date", status=Status.CONFIRMED, value_text=entry.list_date, available_at=entry.entered_at,
                source_type=SourceType.MANUAL, source_id="listing_schedule.csv", extractor="수기 입력", **common),
           Fact(var="short_code", status=Status.CONFIRMED, value_text=entry.stock_code, available_at=entry.entered_at,
                source_type=SourceType.MANUAL, source_id="listing_schedule.csv", extractor="수기 입력", **common)]
    if entry.offer_price is not None:
        out.append(Fact(var="offer_price", unit="KRW", status=Status.CONFIRMED, value_num=entry.offer_price,
                        available_at=entry.entered_at, source_type=SourceType.MANUAL, source_id="listing_schedule.csv",
                        extractor="수기 입력", **common))
    elif registry_row.get("offer_price_status") == "확인" and registry_row.get("offer_price_final") \
            and registry_row.get("offer_price_available_dt"):
        out.append(Fact(var="offer_price", unit="KRW", status=Status.CONFIRMED, value_num=float(registry_row["offer_price_final"]),
                        available_at=dart_available_at(registry_row["offer_price_available_dt"]), source_type=SourceType.DART,
                        source_id=registry_row.get("offer_price_rcept", ""), extractor="dart_terms.final_offer_terms", **common))
    return out


def registry_rows() -> list[dict]:
    with open(config.MART / "dart_ipo_registry.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main(argv=None) -> int:
    import sys
    argv = argv if argv is not None else sys.argv[1:]
    usage = "사용: python -m ops.schedule add YYYYMMDD 회사이름 종목코드 [공모가] | list | check YYYYMMDD"
    if not argv:
        print(usage)
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "add" and 3 <= len(args) <= 4:
        e = add(PATH, args[0], args[1], args[2], args[3] if len(args) == 4 else None)
        late = e.entered_at > datetime.strptime(e.list_date, "%Y%m%d").replace(hour=15, minute=20, tzinfo=KST)
        print(f"추가: {e.list_date} {e.corp_name} {e.stock_code}" + (f" 공모가 {e.offer_price:g}" if e.offer_price else ""))
        if late:
            print("[경고] 상장일 15:20 이후에 입력해서 이 종목은 오늘 판단에 쓰이지 않습니다.")
        return 0
    if cmd == "list":
        for e in sorted(load(PATH), key=lambda x: (x.list_date, x.stock_code)):
            print(f"{e.list_date}  {e.stock_code}  {e.corp_name}  공모가 {e.offer_price if e.offer_price else '-'}  (입력 {e.entered_at:%m-%d %H:%M})")
        return 0
    if cmd == "check" and len(args) == 1:
        reg = registry_rows()
        todays = [e for e in load(PATH) if e.list_date == args[0]]
        for e in todays:
            r = match_registry(e, reg)
            print(f"{e.corp_name} {e.stock_code}: " + (f"DART 연결됨 ({r['ipo_id']})" if r else
                  "DART 레지스트리에서 못 찾음 → '관망(미연결)'로 장부에 남습니다. 회사명을 DART 표기와 같게 하거나 build_dart_registry 를 다시 실행하세요"))
        if not todays:
            print(f"{args[0]} 에 입력된 일정이 없습니다")
        return 0
    print(usage)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
