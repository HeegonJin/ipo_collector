"""랩 추가 조건: 지수·업종 추세, 시장 온도, 구주매출 비중, 업종 매핑. 모두 상장일 이전 자료만 쓰는지 확인한다."""
from lab import features
from lab.features import Series

SECTOR_CFG = {"map": {"26": "전기전자", "21": "제약"}, "fallback_manufacturing": "제조", "fallback_other": "일반서비스"}


def test_series_never_reads_the_listing_day_or_later():
    s = Series({f"2026010{d}": 100.0 + d for d in range(1, 10)})       # 20260101..09: 101..109
    assert s.trailing_ret("20260106", 2) == (105 / 103 - 1) * 100       # 마지막 값은 0105 (0106 자체는 제외)
    assert s.trailing_ret("20260103", 5) is None                        # 자료 부족은 0 이 아니라 None
    assert s.drawdown("20260110", 3) == 0.0                              # 최근 3일 모두 상승 → 고점
    assert Series({"20260101": 100, "20260102": 90, "20260103": 95}).drawdown("20260104", 3) == (95 / 100 - 1) * 100


def test_volatility_is_stdev_of_daily_pct_changes():
    s = Series({"20260101": 100.0, "20260102": 110.0, "20260103": 99.0})
    got = s.volatility("20260104", 2)
    assert abs(got - 14.1421356) < 1e-4 and s.volatility("20260104", 5) is None


def test_ipo_heat_uses_only_earlier_listings():
    hist = [{"list_date": f"2026010{i}", "ret": float(i * 10)} for i in range(1, 8)]
    h = features.ipo_heat(hist, "20260106")                              # 직전 5건: 0101..0105 → 평균 30
    assert h["ipo_heat_ret5"] == 30.0 and h["ipo_heat_cnt30"] == 5
    assert features.ipo_heat(hist, "20260104")["ipo_heat_ret5"] is None   # 5건이 안 되면 None
    assert features.ipo_heat([], "20260104")["ipo_heat_cnt30"] is None


def test_sector_name_mapping_and_fallbacks():
    assert features.sector_name("26110", SECTOR_CFG) == "전기전자"
    assert features.sector_name("24100", SECTOR_CFG) == "제조"            # 제조업인데 표에 없음
    assert features.sector_name("73100", SECTOR_CFG) == "일반서비스"
    assert features.sector_name(None, SECTOR_CFG) is None


def _estk(types, sellers=None):
    groups = [{"title": "증권의종류", "list": types}]
    if sellers is not None:
        groups.append({"title": "매출인에관한사항", "list": sellers})
    return {"asof_max_rcept": types[0]["rcept_no"], "resp": {"group": groups}}


def test_secondary_pct():
    t = [{"rcept_no": "20260109000577", "stkcnt": "1,000"}]
    assert features.secondary_pct(_estk(t, [{"rcept_no": "20260109000577", "slstk": "250"}]), "20260130") == 25.0
    assert features.secondary_pct(_estk(t), "20260130") == 0.0                                  # 매출인 표 없음 = 구주매출 없음
    assert features.secondary_pct(_estk(t, [{"rcept_no": "20260109000577", "slstk": "2,000"}]), "20260130") is None   # 합계 불일치
    assert features.secondary_pct(_estk(t), "20260101") is None                                  # 상장일 이후에 접수된 신고서는 안 씀
    assert features.secondary_pct(None, "20260130") is None


def test_secondary_pct_uses_the_latest_filing_before_listing():
    t = [{"rcept_no": "20260105000001", "stkcnt": "1000"}, {"rcept_no": "20260110000002", "stkcnt": "800"}]
    sellers = [{"rcept_no": "20260105000001", "slstk": "500"}, {"rcept_no": "20260110000002", "slstk": "80"}]
    assert features.secondary_pct(_estk(t, sellers), "20260130") == 10.0


def test_sector_map_names_exist_in_the_krx_index_files():
    """매핑이 가리키는 지수 이름이 실제 KRX 지수 파일에 있는지 (자료가 없으면 건너뜀)."""
    import json
    import pytest
    import config
    from core import settings
    files = sorted((config.RAW / "krx" / "kosdaq_idx").glob("2026*.json")) if (config.RAW / "krx" / "kosdaq_idx").exists() else []
    if not files:
        pytest.skip("kosdaq_idx 자료 없음")
    names = {r["IDX_NM"] for r in json.loads(files[-1].read_text(encoding="utf-8"))}
    cfg = settings.load_sector_map()
    missing = {v for v in cfg["map"].values()} | {cfg["fallback_manufacturing"], cfg["fallback_other"]}
    assert missing <= names, missing - names
