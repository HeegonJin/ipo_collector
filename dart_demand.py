"""DART 원문(document.xml)에서 수요 지표를 뽑는다. 설계도 L1 1순위 코드 파서(수요예측 결과, 확약, 유통가능주식, 청약 결과).

출처와 공개 시점 (둘 다 상장 전에 공시된다 → 상장일 판단에 look-ahead 없이 쓸 수 있다)
  발행조건확정 정정신고서 : 기관 수요예측 경쟁률·참여 건수, 의무보유 확약 신청 수량, 상장 직후 유통가능 물량, 락업 일정
  증권발행실적보고서     : 일반청약 경쟁률, 기관 배정분의 확약기간별 최종 배정 비중

표 배치는 문서마다 조금씩 달라서 '행 이름 + 숫자열' 로 읽고, 합계 열(마지막 칸)을 쓴다. 정정 공시는 정정 전·후 표가 함께 있으므로 마지막 표를 쓴다.
읽은 값은 교차 검증을 통과해야 '확인', 아니면 값은 남기되 '미확인' (결측 ≠ 0, 못 읽은 값은 None).
  수요예측: 표의 열 개수 일치, 수량 ÷ 경쟁률(= 기관 물량)이 공모 주식 수 이하
  확약    : 확약 수량 + 미확약 = 합계 (= 수요예측 참여 수량)
  유통가능: 유통가능 ÷ 상장주식 수가 문장의 비율과 일치 (±0.05%p)
  락업    : 일정 합 = 상장주식 − 유통가능 (문장에서 일부만 읽히는 경우가 많아 대개 '미확인' = 참고용 하한)
  청약    : 기관+일반 최초 배정 ≤ 합계 배정, 확약 비중 합 = 100%
"""
import re

import dart_terms
from core.schema import Status

OK, NO = Status.CONFIRMED.value, Status.UNVERIFIED.value
_TOK = r"(?:[\d,]+(?:\.\d+)?|-|\.)(?=\s|$)"       # 뒤 경계: '6개월 …' 행이 다음 행 이름 '3개월' 의 3 을 숫자로 먹지 않게. '-' 와 '.' 는 빈 칸(0)
_SEQ = rf"((?:\s+{_TOK})+)"
_DEM = re.compile(rf"건수{_SEQ}\s+수량{_SEQ}\s+경쟁률{_SEQ}")
_UNCOMMITTED = re.compile(rf"미확약{_SEQ}\s+(?:총\s*)?(?:합\s*계|계){_SEQ}")       # 합계 행 이름이 '합 계', '계', '총 합계'
_SIMPLE_COMMIT = re.compile(rf"의무보유\s*확약\s*신청내역(.{{0,400}}?)합\s*계{_SEQ}")     # 미확약 행이 없는 간단한 표
_PERIODS = (("6개월", "6m"), ("3개월", "3m"), ("1개월", "1m"), ("15일", "15d"), ("2주일", "15d"), ("2주", "15d"))   # 2주·2주일 은 15일 칸으로 합친다
_FLOAT_A = re.compile(r"([\d.]+)\s*%\s*에\s*해당하는\s*([\d,]+)\s*주\s*(?:는|은)?\s*상장\s*직후\s*유통\s*가능\s*(?:한\s*)?물량")
_FLOAT_B = re.compile(r"([\d,]+)\s*주\s*\(\s*[^)]{0,30}?([\d.]+)\s*%\s*\)\s*(?:는|은)\s*상장\s*직후\s*(?:시장에서\s*)?유통\s*가능\s*(?:한\s*)?물량")
_FLOAT_C = re.compile(r"([\d,]+)\s*주\s*(?:는|은)\s*상장\s*직후\s*시장에서\s*유통\s*가능\s*한\s*물량이며,?\s*상장예정주식수\s*기준으로\s*([\d.]+)\s*%")
_FLOAT_D = re.compile(r"유통\s*불가능\s*한\s*물량이며,?\s*이를\s*제외한\s*([\d,]+)\s*주\s*\(\s*[^)]{0,30}?([\d.]+)\s*%\s*\)")
_TOTAL_BEFORE = re.compile(r"발행주식총수\s*\(?\s*([\d,]+)\s*주")
_LISTED = re.compile(r"상장예정주식수\s*\(?\s*([\d,]+)\s*주")
_LOCK = re.compile(r"([\d,]+)\s*주\s*\(\s*(?:공모\s*후\s*)?[\d.]+\s*%\s*\)\s*(?:는|은|를|가)?\s*상장\s*(?:일(?:로)?\s*부터|후|일\s*이후)\s*"
                   r"(?:(\d+)\s*년)?\s*(?:(\d+)\s*개월)?\s*(?:(\d+)\s*일)?")
_ALLOC_ROW = re.compile(r"(기관투자자|일반투자자)\s+([\d,]+)\s+[\d.]+\s+([\d,]+)\s+([\d,]+)\s+[\d,]+\s+[\d.]+\s+[\d,]+\s+([\d,]+)")
_ALLOC_TOTAL = re.compile(r"\s계\s+([\d,]+)\s")
_FLOAT_TOL_PP = 0.05
_COMMIT_TOTAL_GAP = 0.02          # 확약 표 합계와 수요예측 참여 수량이 이 비율까지 다른 것은 허용 (표 내부 합은 정확히 맞아야 한다)


def _n(tok: str) -> float:
    return 0.0 if tok in ("-", ".") else float(tok.replace(",", ""))


def _toks(group: str) -> list[str]:
    return group.split()


def _empty_demand() -> dict:
    return {"demand_n": None, "demand_qty": None, "demand_ratio": None, "demand_status": NO, "demand_note": "수요예측 결과 표 없음",
            "commit_qty": None, "commit_ratio": None, "commit_status": NO, "commit_note": "확약 표 없음",
            "float_shares": None, "float_pct": None, "listed_shares": None, "float_status": NO, "float_note": "유통가능 문장 없음",
            "lockups": {}, "locked_total": None, "lockup_status": NO}


def _parse_demand_table(text: str, offer_shares, out: dict) -> None:
    found = list(_DEM.finditer(text))
    if not found:
        return
    n, qty, ratio = (_toks(g) for g in found[-1].groups())
    out.update(demand_n=int(_n(n[-1])), demand_qty=int(_n(qty[-1])), demand_ratio=_n(ratio[-1]))
    if not len(n) == len(qty) == len(ratio):
        out.update(demand_status=NO, demand_note=f"열 개수 불일치 (건수 {len(n)}, 수량 {len(qty)}, 경쟁률 {len(ratio)})")
        return
    if offer_shares and out["demand_ratio"]:
        implied = out["demand_qty"] / out["demand_ratio"]          # 기관 배정 대상 물량
        if implied > offer_shares * 1.0001:
            out.update(demand_status=NO, demand_note=f"수량÷경쟁률 {implied:,.0f}주가 공모 주식 {offer_shares:,.0f}주보다 큼")
            return
    out.update(demand_status=OK, demand_note="")


def _qty(tokens: list[str], stride: int) -> int:
    """한 행의 합계 열 수량. 열마다 (건수, 수량) 이면 stride 2, (건수, 수량, 신청가격) 이면 3 이라 수량은 뒤에서 stride-1 번째.
    그 칸이 '-' 인데 다른 열에는 수량이 있으면 열별 수량의 합으로 복원한다 (복원값도 아래 전체 합 검산을 통과해야 쓴다)."""
    tok = tokens[-(stride - 1)] if stride == 2 else tokens[-2]
    if tok in ("-", ".") and len(tokens) % stride == 0 and len(tokens) >= 2 * stride:
        rebuilt = sum(_n(tokens[p]) for p in range(1, len(tokens) - stride, stride))
        return int(rebuilt)
    return int(_n(tok))


def _period_qty(window: str, stride: int = 2) -> dict:
    qty = {key: 0 for _, key in _PERIODS}
    for label, key in _PERIODS:
        rows = list(re.finditer(rf"{label}(?:\s*확약)?{_SEQ}", window))
        if rows:                                                              # 행이 없으면 0 으로 두되 합 검산이 잡아낸다
            qty[key] += _qty(_toks(rows[-1].group(1)), stride)
    return qty


def _parse_simple_commit(text: str, out: dict) -> None:
    """미확약 행이 없는 '의무보유 확약 신청내역' 표: 기간별 (건수, 수량) 과 합계. 비율의 분모는 수요예측 참여 수량."""
    found = list(_SIMPLE_COMMIT.finditer(text))
    if not found:
        return
    qty = _period_qty(found[-1].group(1))
    committed = int(_n(_toks(found[-1].group(2))[-1]))
    base = out["demand_qty"]
    out.update(commit_qty=qty, commit_ratio=committed / base if base else None)
    if sum(qty.values()) != committed:
        out.update(commit_status=NO, commit_note=f"기간별 합 {sum(qty.values()):,} ≠ 확약 합계 {committed:,}")
    elif not base:
        out.update(commit_status=NO, commit_note="수요예측 참여 수량을 몰라 비율을 계산할 수 없음")
    else:
        out.update(commit_status=OK, commit_note="")


def _parse_commit_table(text: str, out: dict) -> None:
    found = list(_UNCOMMITTED.finditer(text))
    if not found:
        return _parse_simple_commit(text, out)
    m = found[-1]
    window = text[max(0, m.start() - 1500): m.start()]
    stride = 3 if "신청가격" in window[window.rfind("건수"):] else 2          # 열마다 신청가격 칸이 더 있는 서식
    unconfirmed, total = _qty(_toks(m.group(1)), stride), _qty(_toks(m.group(2)), stride)
    qty = _period_qty(window, stride)
    committed = sum(qty.values())
    out.update(commit_qty=qty, commit_ratio=committed / total if total else None)
    if committed + unconfirmed != total:
        out.update(commit_status=NO, commit_note=f"확약 {committed:,} + 미확약 {unconfirmed:,} ≠ 합계 {total:,}")
    elif out["demand_qty"] is not None and total != out["demand_qty"]:
        gap = abs(total - out["demand_qty"]) / out["demand_qty"]
        note = f"확약 표 합계 {total:,} 가 수요예측 참여 수량 {out['demand_qty']:,} 와 {gap * 100:.1f}% 다름"
        out.update(commit_status=OK if gap <= _COMMIT_TOTAL_GAP else NO, commit_note=note)   # 표 자체 합은 맞다: 집계 대상이 약간 다른 문서
    else:
        out.update(commit_status=OK, commit_note="")


def _last_float(text: str):
    """(위치, 유통가능 주식 수, 비율 %, 총 주식 수 또는 None). 문장 형태 A~D 중 가장 뒤의 것.
    총 주식 수는 A 문장 바로 앞의 '발행주식총수 (N주)' 에서 읽는다 (없으면 None → 상장예정주식수 문장으로 보완)."""
    cands = []
    for m in _FLOAT_A.finditer(text):
        before = _TOTAL_BEFORE.findall(text[max(0, m.start() - 160): m.start()])
        cands.append((m.start(), _n(m.group(2)), float(m.group(1)), _n(before[-1]) if before else None))
    for rx in (_FLOAT_B, _FLOAT_D):
        cands += [(m.start(), _n(m.group(1)), float(m.group(2)), None) for m in rx.finditer(text)]
    cands += [(m.start(), _n(m.group(1)), float(m.group(2)), None) for m in _FLOAT_C.finditer(text)]
    return max(cands, key=lambda c: c[0]) if cands else None


def _months(y, m, d):
    months = 12 * int(y or 0) + int(m or 0)
    if months:
        return months
    return round(int(d) / 30, 1) if d else None


def _lockup_schedule(region: str) -> dict:
    """'N주(공모 후 x%)는 상장일로부터 K개월/년/일' 문장을 개월 수별 주식 수로 묶는다. 같은 (주식 수, 기간) 은 한 번만 센다."""
    seen, lockups = set(), {}
    for m in _LOCK.finditer(region):
        months = _months(m.group(2), m.group(3), m.group(4))
        key = (m.group(1), months)
        if months is None or key in seen:
            continue
        seen.add(key)
        lockups[months] = lockups.get(months, 0) + int(_n(m.group(1)))
    return lockups


def _parse_float_and_lockups(text: str, out: dict) -> None:
    last = _last_float(text)
    if last:
        pos, shares, pct, total = last
        if total is None:
            listed = _LISTED.findall(text)
            total = _n(listed[-1]) if listed else None
        out.update(float_shares=int(shares), float_pct=pct, listed_shares=int(total) if total else None)
        if total is None:
            out.update(float_status=NO, float_note="총 상장주식 수를 몰라 비율을 검산할 수 없음")
        elif abs(shares / total * 100 - pct) > _FLOAT_TOL_PP:
            out.update(float_status=NO, float_note=f"유통가능 {shares:,.0f} ÷ 상장 {total:,.0f} = {shares / total * 100:.2f}% ≠ 문장 {pct}%")
        else:
            out.update(float_status=OK, float_note="")
    # 정정 전·후가 함께 있으면 마지막 유통가능 문장 뒤만 먼저 보고, 거기 없으면 문서 전체에서 찾는다 (락업 문장이 앞 절에 있는 문서가 있다)
    out["lockups"] = _lockup_schedule(text[last[0]: last[0] + 4000] if last else text) or _lockup_schedule(text)
    if out["listed_shares"] is not None and out["float_shares"] is not None:
        out["locked_total"] = out["listed_shares"] - out["float_shares"]
        lockups = out["lockups"]
        out["lockup_status"] = OK if lockups and abs(sum(lockups.values()) - out["locked_total"]) <= out["locked_total"] * 0.001 else NO


def parse_demand(text: str, offer_shares: float | None = None) -> dict:
    """발행조건확정(정정) 공시 텍스트 → 수요예측·확약·유통가능·락업 일정. offer_shares 는 총 공모 주식 수(검산용, 선택)."""
    out = _empty_demand()
    _parse_demand_table(text, offer_shares, out)
    _parse_commit_table(text, out)
    _parse_float_and_lockups(text, out)
    return out


def parse_allocation(text: str) -> dict:
    """증권발행실적보고서 텍스트 → 일반청약 경쟁률(청약 수량 ÷ 최초 배정 수량), 기관 확약기간별 최종 배정 비중."""
    out = {"retail_ratio": None, "retail_subscribers": None, "final_commit_ratio": None, "final_commit_pct": None,
           "alloc_status": NO, "alloc_note": "청약 및 배정현황 표 없음"}
    rows = {m.group(1): m for m in _ALLOC_ROW.finditer(text)}
    retail, inst = rows.get("일반투자자"), rows.get("기관투자자")
    ok = False
    if retail:
        init, subscribed = _n(retail.group(2)), _n(retail.group(4))
        if init > 0:
            out.update(retail_ratio=subscribed / init, retail_subscribers=int(_n(retail.group(3))), alloc_note="")
            total = _ALLOC_TOTAL.search(text, retail.end())
            used = init + (_n(inst.group(2)) if inst else 0)
            ok = bool(total) and used <= _n(total.group(1))
            if not ok:
                out["alloc_note"] = "최초 배정 합이 합계 배정 수량과 맞지 않음"
    start = text.find("의무보유확약기간별")
    if start >= 0:
        seg = text[start: start + 1800]
        by_qty = "비중" not in seg[: seg.find("미확약")] if "미확약" in seg else False      # 열이 (건수, 수량) 뿐이고 비중 열이 없는 서식
        vals = {}
        for label, key in _PERIODS + (("미확약", "none"),):
            m = re.search(rf"(?:^|\s){label}(?:\s*확약)?{_SEQ}", seg)
            if m:
                vals[key] = _n(_toks(m.group(1))[-1])                  # 합계 열의 비중(%) 또는 수량
        if "none" in vals:
            unc = vals.pop("none")
            if by_qty:
                tot = re.search(rf"\s계{_SEQ}", seg[seg.find("미확약"):])
                total = _n(_toks(tot.group(1))[-1]) if tot else 0
                if total <= 0:
                    ok = False
                    out["alloc_note"] = "확약 배정 합계 수량을 읽지 못함"
                else:
                    pct = {k: v / total * 100 for k, v in vals.items()}
                    out.update(final_commit_ratio=1 - unc / total, final_commit_pct=pct)
                    if abs(sum(vals.values()) + unc - total) > 0.5:
                        ok = False
                        out["alloc_note"] = f"확약 수량 합 {sum(vals.values()) + unc:,.0f} ≠ 배정 합계 {total:,.0f}"
            else:
                pct = vals
                out.update(final_commit_ratio=(100 - unc) / 100, final_commit_pct=pct)
                if abs(sum(pct.values()) + unc - 100) > 0.15:           # 반올림 오차를 허용
                    ok = False
                    out["alloc_note"] = f"확약 비중 합 {sum(pct.values()) + unc:.2f}% ≠ 100%"
    out["alloc_status"] = OK if ok else NO
    return out


def demand_for(rcept_no: str, offer_shares: float | None = None) -> dict:
    return parse_demand(dart_terms.to_text(dart_terms.fetch_document_xml(rcept_no)), offer_shares)


def allocation_for(rcept_no: str) -> dict:
    return parse_allocation(dart_terms.to_text(dart_terms.fetch_document_xml(rcept_no)))
