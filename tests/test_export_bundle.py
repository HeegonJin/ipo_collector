"""스터디용 데이터 묶음: 대상 종목과 코스닥 지수 행만 담고 인증키·장부는 담지 않는다."""
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from tools import export_bundle  # noqa: E402


def test_bundle_keeps_only_study_stocks_index_rows_and_marts(tmp_path, monkeypatch):
    raw, mart = tmp_path / "0_raw", tmp_path / "2_mart"
    (raw / "krx" / "ksq_daily").mkdir(parents=True)
    (raw / "krx" / "kosdaq_idx").mkdir(parents=True)
    mart.mkdir()
    (raw / "krx" / "ksq_daily" / "20250102.json").write_text(json.dumps(
        [{"ISU_CD": "AAAAAA", "TDD_CLSPRC": "1"}, {"ISU_CD": "BBBBBB", "TDD_CLSPRC": "2"}, {"ISU_CD": "CCCCCC", "TDD_CLSPRC": "3"}]), encoding="utf-8")
    (raw / "krx" / "kosdaq_idx" / "20250102.json").write_text(json.dumps(
        [{"IDX_NM": "코스닥", "CLSPRC_IDX": "1"}, {"IDX_NM": "코스피", "CLSPRC_IDX": "2"}]), encoding="utf-8")
    (mart / "dart_ipo_registry.csv").write_text(
        "stock_code,in_trading_universe,pre_sample\nAAAAAA,True,False\nBBBBBB,False,True\nCCCCCC,False,False\n", encoding="utf-8")
    monkeypatch.setattr(config, "RAW", raw)
    monkeypatch.setattr(config, "MART", mart)
    out = export_bundle.build(tmp_path / "out", "20250103")
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        daily = json.loads(z.read("data/0_raw/krx/ksq_daily/20250102.json"))
        idx = json.loads(z.read("data/0_raw/krx/kosdaq_idx/20250102.json"))
    assert {r["ISU_CD"] for r in daily} == {"AAAAAA", "BBBBBB"}          # 대상 + 표본 이전 참고용, 그 밖의 종목은 제외
    assert [r["IDX_NM"] for r in idx] == ["코스닥"]
    assert "data/2_mart/dart_ipo_registry.csv" in names
    assert not any(n.endswith(".env") or "_meta" in n or "ledger" in n for n in names)
