"""전략 실험 앱의 종목별 특징 표. 한 종목 = 한 줄.

특징은 두 종류다. 구분은 앱 화면에도 그대로 보인다.
  pre : 상장 전에 확정되는 값 (확정 공모가의 밴드 내 위치, 공모금액). look-ahead 없이 쓸 수 있다.
  d0  : 상장일 장 마감 뒤에야 정해지는 값 (종가/공모가, 고점 대비 종가, 상장일 코스닥 등락률).
        D0 종가로 진입하면 15:20 판단에는 쓸 수 없는 정보라 결과가 '상한 추정'이다 (D1 시가 진입이면 깨끗하다).
값을 알 수 없으면 0 이 아니라 None 이다 (결측 ≠ 0).
"""
from evaluate import splits as splitlib
from evaluate.outcomes import BarIndex
from store.bars import INDEX_CODE

MAX_OFFSET = 6      # D0 이후 시가를 D+6 까지 모은다 (D1 진입 + 5일 보유)
LIMIT_UP_X = 4 * 0.999   # A0 와 같은 상한가 종가 판정 (공모가 ×4)


def _f(v):
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _split_of(list_date: str, splits: dict) -> str:
    for name in ("train", "valid", "forward"):
        if splitlib.in_split(list_date, name, splits):
            return name
    return "none"


def build_rows(universe: list[dict], terms: list[dict], index: BarIndex, splits: dict) -> list[dict]:
    """universe: 레지스트리 CSV 행(매매 대상), terms: 공모 조건 CSV 행. 상장일 시세가 없는 종목은 건너뛴다."""
    shares = {}
    for t in terms:
        v = _f(t.get("stock_cnt"))
        if v is not None and t["ipo_id"] not in shares:
            shares[t["ipo_id"]] = v
    idx = index.code(INDEX_CODE)
    rows = []
    for r in universe:
        d0, offer = r["list_dd"], _f(r["offer_price_final"])
        bars = index.code(r["stock_code"])
        b0 = bars.get(d0)
        if not b0 or not offer:
            continue
        lo, hi = _f(r.get("band_low")), _f(r.get("band_high"))
        band_pos = (offer - lo) / (hi - lo) if lo is not None and hi is not None and hi > lo else None
        cnt = shares.get(r["ipo_id"])
        prev = index.prev_day(d0)
        i0, ip = idx.get(d0), idx.get(prev) if prev else None
        open_d = {}
        for k in range(MAX_OFFSET + 1):
            day = index.day_after(d0, k)
            open_d[k] = bars[day]["open"] if day in bars else None
        c0, h0 = b0["close"], b0.get("high")
        rows.append({
            "ipo_id": r["ipo_id"], "name": r["corp_name"], "code": r["stock_code"], "list_date": d0,
            "split": _split_of(d0, splits), "offer_price": offer,
            "band_pos": band_pos,
            "offer_amount_bil": cnt * offer / 1e8 if cnt else None,
            "d0_ret_vs_offer": (c0 / offer - 1) * 100 if c0 else None,
            "d0_drop_from_high": (c0 / h0 - 1) * 100 if c0 and h0 else None,
            "d0_index_chg": (i0["close"] / ip["close"] - 1) * 100 if i0 and ip and i0["close"] and ip["close"] else None,
            "close_d0": c0, "open_d": open_d,
            "limit_up": bool(c0 and c0 >= offer * LIMIT_UP_X),
        })
    return rows
