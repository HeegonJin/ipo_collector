"""전략 실험 앱의 로컬 서버: 127.0.0.1 에서만 열리고 JSON API 와 (빌드했다면) 화면 파일을 낸다.

  python -m lab.server 20261029            # http://127.0.0.1:8765
  cd lab/web && npm run dev                # 개발 중에는 Vite(5173)가 /api 를 여기로 넘긴다

평가는 항상 학습(train) 구간에서 한다. 검증(valid) 구간은 /api/validate 로만, 확인 문구와 함께 열린다.
공모/시세 데이터는 로컬 raw 에서 읽고 밖으로 내보내지 않는다 (KRX 약관 Art.11(2)). 내보내기(YAML)는 조건 값만 담는다.
"""
import csv
import json
import mimetypes
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import yaml

import config
from core import settings
from evaluate.outcomes import BarIndex
from lab import engine, guards
from lab.dataset import build_rows
from store.bars import calendar_bars, iter_filtered_bars, iter_index_bars

PORT = 8765
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
MAX_BODY = 1_000_000
WEB_DIST = Path(__file__).resolve().parent / "web" / "dist"


class Lab:
    """API 핸들러 모음. HTTP 와 분리해 두어 화면 없이 테스트한다."""

    def __init__(self, rows, costs, trials: guards.TrialLog, gate: guards.ValidationGate, cfg: dict, meta: dict | None = None):
        self.rows, self.costs, self.trials, self.gate, self.cfg = rows, costs, trials, gate, cfg
        self._meta = meta or {}

    def meta(self) -> dict:
        splits = {}
        for name in ("train", "valid", "forward"):
            splits[name] = sum(1 for r in self.rows if r["split"] == name)
        return {"conditions": engine.CONDITIONS, "entries": engine.ENTRIES, "holds": list(engine.HOLDS),
                "min_n": self.cfg["min_n"], "trials_warn_at": self.cfg["trials_warn_at"],
                "confirm_phrase": self.cfg["confirm_phrase"], "split_sizes": splits, **self._meta}

    def count(self, params: dict) -> dict:
        """조건에 맞는 건수만 알려준다 (수익률은 주지 않는다). 시도로 세지 않는다."""
        res = engine.evaluate(self.rows, params, self.costs, "train")
        return {"n": res["stats"].get("n", 0), "pool": res["pool"]}

    def _trial_info(self, se: float | None) -> dict:
        d = self.trials.distinct()
        return {"distinct": d, "total": self.trials.total(), "warn": d >= self.cfg["trials_warn_at"],
                "warn_at": self.cfg["trials_warn_at"], "chance_best": guards.chance_best(d, se)}

    def evaluate(self, params: dict) -> dict:
        eff = engine.normalize(params)                    # 잘못된 파라미터는 여기서 ValueError, 시도로 세지 않는다
        res = engine.evaluate(self.rows, params, self.costs, "train")
        self.trials.record(eff)
        n = self.cfg["min_n"]
        stats = guards.mask(res["stats"], n)
        return {
            "split": "train", "params": eff, "hash": guards.params_hash(eff), "stats": stats,
            "baseline": guards.mask(res["baseline"], n), "excluded": res["excluded"], "lookahead": res["lookahead"],
            "pool": res["pool"], "design_external": self._design_external(eff),
            "trades": [] if stats["insufficient"] else [
                {k: t[k] for k in ("name", "list_date", "net_ret")} for t in res["trades"]],
            "robustness": guards.robustness(self.rows, params, self.costs, "train", n),
            "trials": self._trial_info(res["stats"].get("se")),
        }

    def validate(self, params: dict, confirm: str, now: datetime | None = None) -> dict:
        return self.gate.open(params, confirm, now or datetime.now())

    @staticmethod
    def _design_external(eff: dict) -> list[str]:
        out = [c for c in eff["conditions"] if not engine.BY_ID[c]["in_design"]]
        if not engine.ENTRIES[eff["entry"]]["in_design"]:
            out.append(eff["entry"])
        return out

    def export(self, params: dict) -> dict:
        """사람이 config/strategy_*_vN.yaml 로 옮길 초안. 임계값 확정은 사람이 새 버전 파일로 한다 (D9)."""
        eff = engine.normalize(params)
        doc = {"entry": eff["entry"], "hold": eff["hold"], "conditions": eff["conditions"],
               "design_external": self._design_external(eff),
               "lookahead_upper_bound": eff["entry"] == "d0_close" and any(
                   engine.BY_ID[c]["phase"] == "d0" for c in eff["conditions"]),
               "trials_distinct": self.trials.distinct(), "evaluated_on": ["train"],
               "note": "탐색 결과 초안이다 (검증 구간 결과는 포함하지 않음). 채택하려면 사람이 새 버전 config 로 고정하고 forward 구간에서 확인한다."}
        return {"yaml": yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)}

    def trials_view(self) -> dict:
        items = self.trials.items()
        return {"distinct": self.trials.distinct(), "total": len(items), "items": list(reversed(items))[:200]}


# ── 실데이터 로더 ────────────────────────────────────────────────
def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_real(end: str, start: str | None = None) -> Lab:
    start = start or config.BUFFER_START
    mart = config.MART
    registry = _read_csv(mart / "dart_ipo_registry.csv")
    universe = [r for r in registry if r["in_trading_universe"] == "True" and r["list_dd"]]
    terms = _read_csv(mart / "dart_offer_terms.csv")
    codes = {r["stock_code"] for r in universe}
    index = BarIndex(list(iter_filtered_bars(start, end, codes)) + calendar_bars(start, end) + list(iter_index_bars(start, end)))
    splits = settings.load_splits()
    years = sorted({int(r["list_dd"][:4]) for r in universe}) or [2023]
    costs = settings.load_costs(years[0], years[-1])
    rows = build_rows(universe, terms, index, splits)
    cfg = guards.load_lab_config()
    trials = guards.TrialLog(config.META / "lab_trials.csv")
    gate = guards.ValidationGate(rows, costs, trials, config.META / "validation_runs.csv", cfg)
    meta = {"data_end": end, "splits": {k: splits[k] for k in ("train", "valid", "forward")}}
    return Lab(rows, costs, trials, gate, cfg, meta)


# ── HTTP ────────────────────────────────────────────────────────
def _host_ok(value: str | None) -> bool:
    if not value:
        return False
    host = value.rsplit(":", 1)[0] if not value.endswith("]") and ":" in value else value
    return host in LOCAL_HOSTS


def make_server(lab: Lab, port: int = PORT) -> ThreadingHTTPServer:
    get_routes = {"/api/meta": lambda: lab.meta(), "/api/trials": lambda: lab.trials_view()}
    post_routes = {
        "/api/count": lambda b: lab.count(b["params"]),
        "/api/evaluate": lambda b: lab.evaluate(b["params"]),
        "/api/validate": lambda b: lab.validate(b["params"], b.get("confirm", "")),
        "/api/export": lambda b: lab.export(b["params"]),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):          # 요청 로그에 조건 값이 남지 않게 조용히
            pass

        def _send(self, status: int, body: dict | bytes, ctype: str = "application/json"):
            payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8" if ctype.startswith("text") or ctype == "application/json" else ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _guard(self) -> bool:
            """DNS 리바인딩·다른 사이트의 요청을 막는다: Host/Origin 이 로컬이어야 한다."""
            if not _host_ok(self.headers.get("Host")):
                self._send(403, {"error": "허용되지 않은 Host"})
                return False
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).hostname not in {"127.0.0.1", "localhost", "::1"}:
                self._send(403, {"error": "허용되지 않은 Origin"})
                return False
            return True

        def do_GET(self):
            if not self._guard():
                return
            path = urlsplit(self.path).path
            if path in get_routes:
                return self._send(200, get_routes[path]())
            if path in post_routes:
                return self._send(405, {"error": "POST 로 요청하세요"})
            if path.startswith("/api/"):
                return self._send(404, {"error": "없는 경로"})
            self._static(path)

        def do_POST(self):
            if not self._guard():
                return
            path = urlsplit(self.path).path
            if path in get_routes:
                return self._send(405, {"error": "GET 으로 요청하세요"})
            if path not in post_routes:
                return self._send(404, {"error": "없는 경로"})
            try:
                size = int(self.headers.get("Content-Length") or 0)
                if size > MAX_BODY:
                    return self._send(413, {"error": "본문이 너무 큼"})
                body = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("본문은 JSON 객체여야 함")
                self._send(200, post_routes[path](body))
            except PermissionError as e:
                self._send(403, {"error": str(e)})
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                self._send(400, {"error": f"잘못된 요청: {e}"})

        def _static(self, path: str):
            root = WEB_DIST.resolve()
            target = (root / path.lstrip("/")).resolve() if path != "/" else root / "index.html"
            if not root.is_dir() or (root not in target.parents and target != root) or not target.is_file():
                return self._send(404, {"error": "화면이 빌드되지 않았습니다 (lab/web 에서 npm run build)"})
            self._send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")

    class LocalServer(ThreadingHTTPServer):
        daemon_threads = True

        def server_bind(self):               # 기본 구현은 getfqdn() 역방향 DNS 조회로 수십 초 걸릴 수 있다
            self.socket.bind(self.server_address)
            self.server_address = self.socket.getsockname()
            self.server_name, self.server_port = "127.0.0.1", self.server_address[1]

    return LocalServer(("127.0.0.1", port), Handler)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("사용: python -m lab.server <데이터 마지막 날짜 YYYYMMDD> [포트]")
        return 2
    lab = load_real(argv[0])
    port = int(argv[1]) if len(argv) > 1 else PORT
    srv = make_server(lab, port)
    print(f"전략 실험 앱 API: http://127.0.0.1:{srv.server_address[1]}  (종목 {len(lab.rows)}개)  Ctrl+C 로 종료")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
