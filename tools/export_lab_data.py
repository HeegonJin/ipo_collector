"""브라우저만으로 도는 실험실(정적 사이트)용 데이터 파일을 만든다: lab/web/public/lab_data.json

종목별 특징 표(종목명·시세에서 뽑은 값 포함)와 비용·설정·화면 메타를 한 파일에 담는다.
KRX 약관 Art.11(2): 이 파일이 든 사이트는 사실상 데이터를 공개하는 것이다. 4인 스터디 안에서만 쓰기로 한 사용자의 결정이며
추측할 수 없는 주소에 올리고 git 에는 넣지 않는다 (lab/web/public/lab_data.json 은 .gitignore).

  python tools/export_lab_data.py 20261029
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.server import load_real  # noqa: E402

OUT = ROOT / "lab" / "web" / "public" / "lab_data.json"


def export(end: str, out: Path = OUT) -> Path:
    lab = load_real(end)
    rows = [{**r, "open_d": {str(k): v for k, v in r["open_d"].items()}} for r in lab.rows]
    meta = lab.meta()
    doc = {"meta": meta, "rows": rows, "costs": {**lab.costs, "kosdaq_sell_tax": {str(k): v for k, v in lab.costs["kosdaq_sell_tax"].items()}},
           "cfg": lab.cfg}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    path = export(sys.argv[1] if len(sys.argv) > 1 else "20261029")
    print(f"[lab] {path} ({path.stat().st_size / 1e3:.0f} KB)")
