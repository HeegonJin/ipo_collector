"""정적 실험실(브라우저, lab/web/src/engine.ts)이 파이썬 엔진·가드와 같은 숫자를 내는지 본다.

lab_data.json(tools/export_lab_data.py, 로컬 전용)과 node, lab/web/node_modules 가 있어야 한다. 없으면 건너뛴다.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab import engine, guards  # noqa: E402

DATA = ROOT / "lab" / "web" / "public" / "lab_data.json"
ESBUILD = ROOT / "lab" / "web" / "node_modules" / ".bin" / "esbuild"
pytestmark = pytest.mark.skipif(not (DATA.exists() and ESBUILD.exists() and shutil.which("node")), reason="lab_data.json·node·esbuild 가 필요함")

CASES = [
    {"entry": "d0_close", "hold": 1, "conditions": {}},
    {"entry": "d1_open", "hold": 3, "conditions": {"demand_ratio": {"enabled": True, "lo": 0, "hi": 1000}}},
    {"entry": "d0_close", "hold": 5, "conditions": {"float_pct": {"enabled": True, "lo": 20, "hi": 60}, "d0_ret_vs_offer": {"enabled": True, "lo": -50, "hi": 100}}},
    {"entry": "d1_open", "hold": 1, "conditions": {"offer_amount_bil": {"enabled": True, "lo": 0, "hi": 500}, "final_commit_pct": {"enabled": True, "lo": 10, "hi": 100}}},
]

JS = """
import {Engine, mask, chanceBest} from "./engine.ts";
import fs from "node:fs";
const d = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const e = new Engine(d.meta.conditions, d.rows, d.costs, d.cfg);
const out = JSON.parse(process.argv[3]).map((p) => {
  const eff = e.normalize(p); const r = e.evaluate(eff, "train");
  return {stats: r.stats, baseline: r.baseline, excluded: r.excluded, lookahead: r.lookahead, pool: r.pool,
          trades: r.trades.map((t) => t.net_ret), robustness: e.robustness(p, "train")};
});
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js_results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("parity")
    (tmp / "run.ts").write_text(JS.replace('"./engine.ts"', f'"{ROOT / "lab/web/src/engine.ts"}"'), encoding="utf-8")
    subprocess.run([str(ESBUILD), str(tmp / "run.ts"), "--bundle", "--platform=node", "--format=esm", f"--outfile={tmp / 'run.mjs'}"],
                   check=True, capture_output=True)
    out = subprocess.run(["node", str(tmp / "run.mjs"), str(DATA), json.dumps(CASES)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


@pytest.fixture(scope="module")
def py_setup():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    rows = [{**r, "open_d": {int(k): v for k, v in r["open_d"].items()}} for r in d["rows"]]
    costs = {**d["costs"], "kosdaq_sell_tax": {int(k): v for k, v in d["costs"]["kosdaq_sell_tax"].items()}}
    return rows, costs, d["cfg"]


def close(a, b):
    if isinstance(a, dict):
        assert set(a) == set(b), (a, b)
        for k in a:
            close(a[k], b[k])
    elif isinstance(a, list):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            close(x, y)
    elif isinstance(a, float) or isinstance(b, float):
        assert a == pytest.approx(b, rel=1e-9, abs=1e-12), (a, b)
    else:
        assert a == b, (a, b)


@pytest.mark.parametrize("i", range(len(CASES)))
def test_browser_engine_matches_python(i, js_results, py_setup):
    rows, costs, cfg = py_setup
    p = CASES[i]
    res = engine.evaluate(rows, p, costs, "train")
    js = js_results[i]
    close(js["stats"], res["stats"])
    close(js["baseline"], res["baseline"])
    close(js["excluded"], res["excluded"])
    assert js["lookahead"] == res["lookahead"] and js["pool"] == res["pool"]
    close(js["trades"], [t["net_ret"] for t in res["trades"]])
    rob = guards.robustness(rows, p, costs, "train", cfg["min_n"])
    assert js["robustness"]["verdict"] == rob["verdict"]
    close(js["robustness"]["neighbors"], rob["neighbors"])
