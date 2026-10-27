"""가짜 KRX 응답으로 탐지·제외·계산 로직 검증. 실행: python -m pytest tests -q"""
import csv
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import build_sample  # noqa: E402
import report  # noqa: E402


def row(code, name, close, cmp_prev, opn=None, srt=None):
    return {"ISU_CD": code, "ISU_SRT_CD": srt or code, "ISU_NM": name, "SECT_TP_NM": "벤처기업부",
            "TDD_CLSPRC": f"{close:,.0f}", "CMPPREVDD_PRC": str(cmp_prev), "FLUC_RT": "0",
            "TDD_OPNPRC": str(opn if opn is not None else close), "TDD_HGPRC": str(close),
            "TDD_LWPRC": str(close), "ACC_TRDVOL": "1000", "ACC_TRDVAL": "1000000",
            "MKTCAP": "100000000000", "LIST_SHRS": "10000000"}


def idx(close, opn, chg):
    return [{"IDX_NM": "코스닥", "CLSPRC_IDX": str(close), "OPNPRC_IDX": str(opn), "FLUC_RT": str(chg)},
            {"IDX_NM": "코스닥 150", "CLSPRC_IDX": "1", "OPNPRC_IDX": "1", "FLUC_RT": "0"}]


def setup(tmp):
    config.RAW = tmp / "0_raw"; config.MART = tmp / "2_mart"; config.META = tmp / "_meta"; config.ROOT = tmp
    config.BUFFER_START, config.SAMPLE_START = "20230103", "20230105"
    days = {
        # 1/3 (여유 구간): 기존 종목 OLD, 코넥스 종목 KNX1
        "20230103": ([row("OLD", "기존", 1000, 0)], [row("KNX1", "코넥스기업", 5000, 0)], idx(700, 700, 0)),
        "20230104": ([row("OLD", "기존", 1000, 0)], [row("KNX1", "코넥스기업", 5000, 0)], idx(700, 700, 0)),
        # 1/5: 신규 IPO A(공모가 10,000 → 종가 6,800), 스팩, 코넥스 이전, 상한가 IPO
        "20230105": ([row("OLD", "기존", 1000, 0),
                      row("A", "엘리스테스트", 6800, -3200),
                      row("SP", "OO스팩5호", 2000, 0),
                      row("KNX1", "코넥스기업", 6000, 1000),
                      row("LU", "상한가기업", 40000, 30000)],
                     [], idx(700, 700, -3.33)),
        # 1/6: 다음 날 시가
        "20230106": ([row("OLD", "기존", 1000, 0), row("A", "엘리스테스트", 7000, 200, opn=7700),
                      row("SP", "OO스팩5호", 2000, 0), row("KNX1", "코넥스기업", 6000, 0),
                      row("LU", "상한가기업", 39000, -1000, opn=36000)],
                     [], idx(710, 707, 1.4)),
    }
    for d, (ksq, knx, ix) in days.items():
        for svc, rows in (("ksq_daily", ksq), ("knx_daily", knx), ("kosdaq_idx", ix)):
            p = config.RAW / "krx" / svc / f"{d}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def test_pipeline():
    tmp = Path(tempfile.mkdtemp())
    setup(tmp)
    rows = build_sample.build("20230106", tag="t")
    by = {r["code"]: r for r in rows}

    assert "OLD" not in by                       # 여유 구간 종목은 신규 아님
    assert set(by) == {"A", "SP", "KNX1", "LU"}
    assert by["SP"]["excluded"] == "스팩·리츠"
    assert by["KNX1"]["excluded"] == "코넥스 이전상장"
    assert by["A"]["excluded"] == ""

    a = by["A"]
    assert a["offer_price_est"] == 10000         # 공모가 = 종가 − 전일대비
    assert abs(a["d0_close_vs_offer"] - (-0.32)) < 1e-9
    assert abs(a["gross_ret"] - (7700 / 6800 - 1)) < 1e-9
    buy = 6800 * (1 + 0.00015 + 0.0025)
    sell = 7700 * (1 - 0.00015 - 0.0025 - 0.0020)
    assert abs(a["net_ret"] - (sell / buy - 1)) < 1e-9
    assert a["net_ret"] < a["gross_ret"]
    assert abs(a["kosdaq_overnight"] - (707 / 700 - 1)) < 1e-9
    assert a["kosdaq_d0_chg_pct"] == -3.33

    assert by["LU"]["buy_at_limit_up"] is True   # 공모가 10,000 × 4 = 40,000
    assert a["buy_at_limit_up"] is False

    sample = config.MART / "ipo_sample_t.csv"
    assert sample.exists() and (config.META / "missing_t.md").exists()
    with open(sample, encoding="utf-8-sig") as f:
        assert len(list(csv.DictReader(f))) == 4

    out = report.write(sample)
    text = out.read_text(encoding="utf-8")
    assert "기대값 > 0: 예" in text and "| 비용 차감 후 | 2 |" in text


if __name__ == "__main__":
    test_pipeline(); print("OK")
