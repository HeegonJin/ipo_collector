"""공유용 정적 페이지(share/)를 만든다: 집계 결과 문서(results/*.md)만 HTML 로 바꾼다.

종목별 시세·종목명이 들어간 자료(data/, 실험실 앱의 거래 목록)는 넣지 않는다 (KRX 약관 Art.11(2): 제3자 제공 금지).
집계 통계에는 'KRX statistical information' 표기를 남긴다 (Art.10(3)) — 원본 문서에 이미 들어 있고, 아래에서 없으면 만들기를 멈춘다.

  python tools/build_share.py          # share/ 생성
  npx netlify-cli deploy --dir share   # (미리보기) / --prod 로 공개
"""
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "share"
DOCS = [  # (파일, 메뉴 이름)
    ("2026-10-31_기초통계_train_v1.md", "기초 통계"),
    ("2026-10-31_A후보탐색_train_v1.md", "전략 A 후보"),
    ("2026-10-31_B_v1_train.md", "전략 B"),
    ("2026-10-31_C_v1_train.md", "전략 C"),
]
NOTICE = "KRX statistical information"
CSS = """:root{--bg:#fafaf8;--text:#1d1d1b;--muted:#6b6b66;--line:#dcdcd6;--accent:#2a5bd7;--code:#f0f0ec}
@media(prefers-color-scheme:dark){:root{--bg:#161615;--text:#ecece8;--muted:#9b9b94;--line:#35352f;--accent:#7ea2ff;--code:#222220}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.65 -apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}
main{max-width:860px;margin:0 auto;padding:20px 16px 60px}nav{display:flex;flex-wrap:wrap;gap:6px 14px;padding:12px 0;border-bottom:1px solid var(--line);margin-bottom:18px}
nav a{color:var(--accent);text-decoration:none}nav a.on{font-weight:700;text-decoration:underline}h1{font-size:23px}h2{font-size:18px;margin-top:28px}h3{font-size:15px}
table{border-collapse:collapse;width:100%;font-size:13px;display:block;overflow-x:auto}th,td{padding:5px 9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}
code,pre{background:var(--code);border-radius:6px;font-size:13px}code{padding:1px 5px}pre{padding:10px;overflow:auto}pre code{padding:0}
.muted,footer{color:var(--muted);font-size:13px}footer{border-top:1px solid var(--line);margin-top:34px;padding-top:12px}"""


def inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)


def md_to_html(md: str) -> str:
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1
        elif ln.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in lines[i:j] if not re.match(r"^\|[\s:|-]+\|$", r)]
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:]) + "</tbody></table>")
            i = j
        elif re.match(r"^#{1,3} ", ln):
            n = len(ln.split(" ")[0])
            out.append(f"<h{n}>{inline(ln[n + 1:])}</h{n}>")
            i += 1
        elif ln.startswith("- "):
            j = i
            while j < len(lines) and lines[j].startswith("- "):
                j += 1
            out.append("<ul>" + "".join(f"<li>{inline(x[2:])}</li>" for x in lines[i:j]) + "</ul>")
            i = j
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
            i += 1
        else:
            i += 1
    return "\n".join(out)


def page(title: str, body: str, current: str) -> str:
    links = [("index.html", "처음"), *[(Path(f).stem + ".html", n) for f, n in DOCS], ("local.html", "직접 실행하기")]
    nav = "".join(f'<a href="{h}"{" class=on" if h == current else ""}>{n}</a>' for h, n in links)
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>{html.escape(title)}</title><style>{CSS}</style></head><body><main><nav>{nav}</nav>{body}'
            f'<footer>이 페이지는 <b>{NOTICE}</b>(한국거래소 통계정보)와 DART 공시로 만든 집계 결과이며, 모의투자 연구용입니다. '
            f'원천 데이터는 비상업 목적으로만 쓰고 제3자에게 제공하지 않습니다. 투자 권유가 아닙니다.</footer></main></body></html>')


INDEX = """<h1>코스닥 IPO 신호 에이전트 — 연구 결과 공유</h1>
<p>코스닥 공모 신규상장 종목을 대상으로 한 <b>모의투자 전용</b> 연구입니다. 무료 공개 자료(KRX·DART)만 쓰고, 종목별 시세는 이 페이지에 싣지 않았습니다. 아래는 모두 <b>집계 결과</b>입니다.</p>
<h2>지금까지의 결론</h2>
<ul><li>학습 구간(2023-07 ~ 2025-06 상장 142종목)에서 전략 A(상장일 종가 매수 → 다음 날 시가 매도)는 비용을 빼면 뚜렷한 기대값이 없었습니다.</li>
<li>전략 B(공모 실패 종목의 반등)는 14건으로 표본이 너무 적고, 전략 C(보호예수 해제 후 안정)는 52건에서 평균이 마이너스였습니다.</li>
<li>검증 구간(2025-07 ~ 2026-10)은 열지 않았습니다. 규칙 숫자는 결과를 보기 전에 고정했습니다.</li></ul>
<p class="muted">표본이 작아 통계적 유의성은 검정하지 않았습니다. 숫자를 맹신하지 마세요.</p>"""

LOCAL = """<h1>직접 실행하기</h1>
<p>종목별 시세는 KRX 약관상 제3자에게 줄 수 없어서, 실험실 앱은 각자 자기 KRX·DART 키로 로컬에서 돌립니다.</p>
<h2>준비</h2>
<pre><code>git clone https://github.com/HeegonJin/ipo_collector.git
cd ipo_collector
python -m venv .venv &amp;&amp; .venv/bin/pip install requests python-dotenv pyyaml pytest
cp .env.example .env     # KRX_API_KEY, DART_API_KEY 입력 (KRX 포털에서 서비스별 승인 필요)</code></pre>
<h2>데이터 수집 → 앱 실행</h2>
<pre><code>.venv/bin/python krx_api.py 20261029
.venv/bin/python dart_list.py 20220701 20261029
.venv/bin/python build_dart_registry.py 20220701 20261029 20261029
.venv/bin/python build_demand_mart.py
.venv/bin/python -m lab.server 20261029     # http://127.0.0.1:8765
cd lab/web &amp;&amp; npm install &amp;&amp; npm run build   # 화면 빌드(최초 1회)</code></pre>
<p>앱은 내 컴퓨터(127.0.0.1)에서만 열립니다. “모의 운영” 탭에서 상장 일정을 직접 입력하고 일일 판단 작업을 실행합니다.</p>"""


def main() -> int:
    OUT.mkdir(exist_ok=True)
    for f in OUT.glob("*.html"):
        f.unlink()
    for name, label in DOCS:
        md = (ROOT / "results" / name).read_text(encoding="utf-8")
        if NOTICE not in md:
            print(f"중단: {name} 에 '{NOTICE}' 표기가 없습니다")
            return 1
        (OUT / (Path(name).stem + ".html")).write_text(page(label, md_to_html(md), Path(name).stem + ".html"), encoding="utf-8")
    (OUT / "index.html").write_text(page("IPO 신호 에이전트", INDEX, "index.html"), encoding="utf-8")
    (OUT / "local.html").write_text(page("직접 실행하기", LOCAL, "local.html"), encoding="utf-8")
    (OUT / "_headers").write_text("/*\n  X-Robots-Tag: noindex\n  X-Frame-Options: DENY\n", encoding="utf-8")
    print(f"[share] {len(list(OUT.glob('*.html')))}페이지 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
