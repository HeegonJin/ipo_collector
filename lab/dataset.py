"""전략 실험 앱의 종목별 특징 표. 한 종목 = 한 줄.

특징은 두 종류다. 구분은 앱 화면에도 그대로 보인다.
  pre : 상장 전에 공시되는 값 (기관 수요예측 경쟁률, 일반청약 경쟁률, 확약률, 유통가능 비율; build_demand_mart). look-ahead 없이 쓸 수 있다.
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


def _confirmed(row: dict, status_col: str, value):
    """교차 검증을 통과(확인)한 값만 쓴다. 미확인·빈 칸은 None (결측 ≠ 0)."""
    return value if row.get(status_col) == "확인" else None


def _demand_features(d: dict) -> dict:
    ratio = _f(d.get("final_commit_ratio"))
    return {
        "demand_ratio": _confirmed(d, "demand_status", _f(d.get("demand_ratio"))),
        "retail_ratio": _confirmed(d, "alloc_status", _f(d.get("retail_ratio"))),
        "final_commit_pct": _confirmed(d, "alloc_status", ratio * 100 if ratio is not None else None),
        "float_pct": _confirmed(d, "float_status", _f(d.get("float_pct"))),
    }


EXTRA_KEYS = ("ipo_heat_ret5", "ipo_heat_cnt30", "idx_ret20", "idx_ret60", "idx_dd60", "idx_vol20",
              "sector_ret20", "sector_rel20", "secondary_pct")


def build_rows(universe: list[dict], index: BarIndex, splits: dict, demand: dict | None = None,
               sizes: dict | None = None, extra: dict | None = None) -> list[dict]:
    """universe: 레지스트리 CSV 행(매매 대상), demand: {ipo_id: 수요 마트 행} (data/2_mart/dart_demand.csv),
    sizes: {ipo_id: 공모 규모(억원)} (모르면 키 없음 → None). 상장일 시세가 없는 종목은 건너뛴다."""
    demand, sizes, extra = demand or {}, sizes or {}, extra or {}
    idx = index.code(INDEX_CODE)
    rows = []
    for r in universe:
        d0, offer = r["list_dd"], _f(r["offer_price_final"])
        bars = index.code(r["stock_code"])
        b0 = bars.get(d0)
        if not b0 or not offer:
            continue
        prev = index.prev_day(d0)
        i0, ip = idx.get(d0), idx.get(prev) if prev else None
        open_d = {}
        for k in range(MAX_OFFSET + 1):
            day = index.day_after(d0, k)
            open_d[k] = bars[day]["open"] if day in bars else None
        c0, h0 = b0["close"], b0.get("high")
        dem = _demand_features(demand.get(r["ipo_id"], {}))
        listed = _confirmed(demand.get(r["ipo_id"], {}), "float_status", _f(demand.get(r["ipo_id"], {}).get("listed_shares")))
        float_sh = listed * dem["float_pct"] / 100 if listed and dem["float_pct"] else None
        rows.append({
            "ipo_id": r["ipo_id"], "name": r["corp_name"], "code": r["stock_code"], "list_date": d0,
            "split": _split_of(d0, splits), "offer_price": offer,
            **dem,
            "offer_amount_bil": sizes.get(r["ipo_id"]),
            "offer_mcap_bil": offer * listed / 1e8 if listed else None,
            **{k: extra.get(r["ipo_id"], {}).get(k) for k in EXTRA_KEYS},
            "d0_mcap_bil": c0 * listed / 1e8 if listed and c0 else None,
            "d0_float_turnover_pct": b0["volume"] / float_sh * 100 if float_sh and b0.get("volume") else None,
            "d0_open_vs_offer": (b0["open"] / offer - 1) * 100 if b0.get("open") else None,
            "d0_ret_vs_offer": (c0 / offer - 1) * 100 if c0 else None,
            "d0_drop_from_high": (c0 / h0 - 1) * 100 if c0 and h0 else None,
            "d0_index_chg": (i0["close"] / ip["close"] - 1) * 100 if i0 and ip and i0["close"] and ip["close"] else None,
            "close_d0": c0, "open_d": open_d,
            "limit_up": bool(c0 and c0 >= offer * LIMIT_UP_X),
        })
    return rows
