"""스터디 팀원에게 나눠 줄 데이터 묶음(zip)을 만든다. 팀원은 인증키 없이 로컬에서 실험실 앱을 돌릴 수 있다.

담는 것: 매매 대상·표본 이전(참고용) 종목의 KRX 일별 시세 행, 코스닥 지수 행, data/2_mart 의 CSV.
담지 않는 것: 전체 종목 시세, 인증키(.env), 장부·시도 기록(data/_meta, data/ledger) — 개인 기록이다.

KRX OPEN API 약관 Art.11(2)는 제3자 제공을 금지한다. 이 묶음은 4인 스터디 안에서만 쓰기로 한 약속으로 나누는 것이며
GitHub·Netlify 같은 공개 주소에는 올리지 않는다 (bundle/ 은 git 에서 제외).

  python tools/export_bundle.py                # bundle/ipo_study_data_<오늘>.zip
팀원: 저장소를 받은 뒤 zip 을 저장소 폴더에서 풀고 python -m lab.server <끝 날짜> 로 앱을 연다 (zip 안 README 참고).
"""
import csv
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from build_sample import short_code  # noqa: E402

README = """IPO 전략 실험실 데이터 묶음 ({today})

[약속] 이 파일은 스터디 4인 안에서만 씁니다. 다른 사람에게 주거나 인터넷(GitHub, 클라우드 공유 링크 공개, 메신저 단체방 등)에 올리지 않습니다.
데이터 출처: KRX statistical information(한국거래소 통계정보), DART 공시. 비상업 연구용입니다.

[쓰는 법]
1) git clone https://github.com/HeegonJin/ipo_collector.git  →  cd ipo_collector
2) python -m venv .venv && .venv/bin/pip install requests python-dotenv pyyaml pytest
3) 이 zip 을 저장소 폴더(ipo_collector/)에서 풉니다:  unzip ipo_study_data_{today}.zip   (data/ 폴더가 생깁니다)
4) 앱 실행:  .venv/bin/python -m lab.server {end}      → 브라우저에서 http://127.0.0.1:8765
   (화면은 lab/web 에서 npm install && npm run build 를 한 번 해야 보입니다)
인증키(.env)는 필요 없습니다. 이 묶음에 든 기간: ~{end}.
"""


def _codes(mart: Path) -> set:
    with open(mart / "dart_ipo_registry.csv", encoding="utf-8-sig", newline="") as f:
        return {r["stock_code"] for r in csv.DictReader(f)
                if r["stock_code"] and (r["in_trading_universe"] == "True" or r.get("pre_sample") == "True")}


def build(out_dir: Path, today: str | None = None) -> Path:
    today = today or date.today().strftime("%Y%m%d")
    codes = _codes(config.MART)
    out = Path(out_dir) / f"ipo_study_data_{today}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    last = ""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((config.RAW / "krx" / "ksq_daily").glob("*.json")):
            rows = [r for r in json.loads(p.read_text(encoding="utf-8")) if short_code(r) in codes]
            if rows:
                last = max(last, p.stem)
                z.writestr(f"data/0_raw/krx/ksq_daily/{p.name}", json.dumps(rows, ensure_ascii=False))
        for p in sorted((config.RAW / "krx" / "kosdaq_idx").glob("*.json")):
            rows = [r for r in json.loads(p.read_text(encoding="utf-8")) if r.get("IDX_NM") == "코스닥"]
            if rows:
                z.writestr(f"data/0_raw/krx/kosdaq_idx/{p.name}", json.dumps(rows, ensure_ascii=False))
        for p in sorted(config.MART.glob("*.csv")):
            z.write(p, f"data/2_mart/{p.name}")
        z.writestr("README_먼저읽기.txt", README.format(today=today, end=last))
    return out


if __name__ == "__main__":
    path = build(ROOT / "bundle")
    print(f"[bundle] {path} ({path.stat().st_size / 1e6:.1f} MB) — 공개 주소에 올리지 말고 팀원에게만 직접 전달하세요")
