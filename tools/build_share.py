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
CSS = """:root{--panel:#fff;--navy:#14213D;--rust:#b5472f;--bg:#fafaf8;--text:#1d1d1b;--muted:#6b6b66;--line:#dcdcd6;--accent:#2a5bd7;--code:#f0f0ec}
@media(prefers-color-scheme:dark){:root{--panel:#1d1d1b;--rust:#e08a73;--bg:#161615;--text:#ecece8;--muted:#9b9b94;--line:#35352f;--accent:#7ea2ff;--code:#222220}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.65 -apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 60px}nav{display:flex;flex-wrap:wrap;gap:6px 14px;padding:12px 0;border-bottom:1px solid var(--line);margin-bottom:18px}
nav a{color:var(--accent);text-decoration:none}nav a.on{font-weight:700;text-decoration:underline}h1{font-size:23px}h2{font-size:18px;margin-top:28px}h3{font-size:15px}
table{border-collapse:collapse;width:100%;font-size:13px;display:block;overflow-x:auto}th,td{padding:5px 9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}
code,pre{background:var(--code);border-radius:6px;font-size:13px}code{padding:1px 5px}pre{padding:10px;overflow:auto}pre code{padding:0}
.hero{padding:34px 0 10px}.hero h1{font-size:40px;margin:4px 0}.eyebrow{color:var(--accent);font-weight:700;margin:0}
.band{margin:26px -16px;padding:26px 16px;border-radius:14px;background:var(--panel)}.band.dark{background:var(--navy);color:#f1f3f8}.band.dark .card{background:#1e2f55;border-color:#1e2f55}.band.dark a{color:#8fd3e2}
.cards{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));margin:14px 0}.cards.c2{grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}.cards.c4{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.card{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:var(--bg)}.card h3{margin:0 0 6px;font-size:16px}.card p{margin:0}.warn{color:var(--rust)}
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
    links = [("index.html", "소개"), *[(Path(f).stem + ".html", n) for f, n in DOCS], ("local.html", "직접 실행하기")]
    nav = "".join(f'<a href="{h}"{" class=on" if h == current else ""}>{n}</a>' for h, n in links)
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>{html.escape(title)}</title><style>{CSS}</style></head><body><main><nav>{nav}</nav>{body}'
            f'<footer>이 페이지는 <b>{NOTICE}</b>(한국거래소 통계정보)와 DART 공시로 만든 집계 결과이며, 모의투자 연구용입니다. '
            f'원천 데이터는 비상업 목적으로만 쓰고 제3자에게 제공하지 않습니다. 투자 권유가 아닙니다.</footer></main></body></html>')


def cards(items, cols=3):
    return f'<div class="cards c{cols}">' + "".join(f"<div class=card><h3>{t}</h3><p>{d}</p></div>" for t, d in items) + "</div>"


def band(title, inner, dark=False):
    return f'<section class="band{" dark" if dark else ""}"><h2>{title}</h2>{inner}</section>'


INTRO_BANDS = [
    band("무엇을 만드는 프로젝트인가요?",
         "<p><b>IPO</b>는 회사가 처음 주식시장에 올라(상장) 일반 투자자에게 주식을 파는 일입니다. 처음 파는 가격이 <b>공모가</b>, 거래가 시작되는 날이 <b>상장일(D0)</b>, 그 다음 거래일이 <b>D1</b>입니다.</p>"
         + cards([("대상", "코스닥 공모 신규상장 종목 (스팩·리츠 제외)"), ("목표", "“사도 되는지 / 보류인지” 신호 만들기. 모의투자 전용"),
                  ("자료", "무료 공개 자료만 사용: KRX 일별 시세, DART 공시")])),
    band("백테스트 = 과거 데이터로 하는 가상 매매",
         "<p>“상장일 종가에 사서 다음 날 시가에 팔았다면?”을 과거 142개 종목에 그대로 적용해 봅니다. 믿을 만하려면 세 가지 약속을 지켜야 합니다.</p>"
         + cards([("1. 미래를 미리 보지 않기", "판단 시각에 이미 공개된 값만 씁니다. 공시와 시세마다 “언제부터 알 수 있는지”를 기록합니다."),
                  ("2. 비용 빼고 계산", "수수료, 슬리피지(원하는 가격에 못 사는 손해), 매도세를 모두 차감한 순수익률로 봅니다."),
                  ("3. 연습과 시험 분리", "조건을 고르는 학습 구간과, 마지막에 한 번만 여는 검증 구간을 나눕니다.")]), dark=True),
    band("실험실 앱은 네 단계입니다",
         cards([("1. 진입 · 보유", "언제 사서 며칠 들고 있을지 고릅니다 (상장일 종가 또는 다음 날 시가, 1·3·5거래일)"),
                ("2. 종목 조건", "켜고 슬라이더로 범위를 정합니다"), ("3. 실행", "학습 구간에서 계산합니다. 실행할 때마다 시도 횟수로 기록됩니다"),
                ("4. 결과 읽기", "평균만 보지 않고 경고를 확인합니다")], 4)
         + "<p class=muted>슬라이더를 움직이는 동안에는 “조건에 맞는 거래 건수”만 바뀝니다. 수익률은 실행을 눌러야 나옵니다. 좋은 숫자가 나올 때까지 조건을 만지는 것(과적합)을 막기 위해서입니다.</p>"),
    band("조절할 수 있는 값들",
         "<table><thead><tr><th>조건</th><th>쉬운 뜻</th><th>알 수 있는 때</th></tr></thead><tbody>"
         "<tr><td>수요예측 경쟁률</td><td>기관 투자자가 공모에 얼마나 몰렸나 (배)</td><td>상장 전</td></tr>"
         "<tr><td>일반 청약 경쟁률</td><td>개인 투자자 청약 인기</td><td>상장 전</td></tr>"
         "<tr><td>의무확약 비율</td><td>일정 기간 팔지 않겠다고 약속한 물량</td><td>상장 전</td></tr>"
         "<tr><td>유통가능 비율</td><td>상장 직후 바로 팔 수 있는 주식 비중</td><td>상장 전</td></tr>"
         "<tr><td>공모 규모(억 원)</td><td>공모가 × 새로 판 주식 수</td><td>상장 전</td></tr>"
         "<tr><td>첫날 등락 · 고점 대비</td><td>상장일 시가·종가가 공모가·고점과 비교해 어땠나</td><td class=warn>상장일 마감 후</td></tr></tbody></table>"
         "<p class=muted>상장일 마감 후에야 아는 값을 상장일 종가 매수와 함께 쓰면 현실에서 불가능한 판단이라, 앱이 “상한 추정” 경고를 띄웁니다.</p>"),
    band("결과 숫자, 이렇게 읽으세요",
         cards([("건수", "조건에 맞은 거래 수. 30건 미만이면 앱이 숫자를 가립니다."),
                ("평균 vs 중앙값", "몇 종목이 평균을 끌어올렸는지 확인합니다. 중앙값이 마이너스면 대부분은 손실입니다."),
                ("승률 · 평균 이익/손실", "자주 이겨도 질 때 크게 잃으면 손해입니다."),
                ("기준선과 비교", "조건 없이 전부 산 결과보다 나은지 봅니다.")], 2), dark=True),
    band("우연에 속지 않게 하는 장치",
         "<p>조건을 계속 바꾸다 보면, 효과가 없어도 어느 한 조합은 우연히 좋게 나옵니다.</p>"
         + cards([("최소 표본 30건", "건수가 모자라면 수익률 숫자를 보여 주지 않습니다."),
                  ("시도 횟수와 우연 최고치", "몇 가지 조합을 봤는지 세고, 그만큼 시도하면 우연히 나올 최고 평균을 알려 줍니다."),
                  ("이웃 구간 견고성", "기준값을 한 칸 옮겨도 결과가 비슷해야 합니다. 한 점에서만 좋으면 “취약”."),
                  ("검증 구간 1회 잠금", "마지막 시험 문제는 확인 문구를 입력해야 열리고, 열 때마다 기록됩니다.")], 2)),
    band("지금까지의 결과: 뚜렷한 우위는 없음",
         "<p>학습 구간(2023-07 ~ 2025-06 상장 142종목), 비용 차감 후 수익률입니다.</p>"
         "<table><thead><tr><th>전략</th><th>건수</th><th>평균</th><th>중앙값</th><th>승률</th></tr></thead><tbody>"
         "<tr><td>A3 종가가 공모가 아래 → 다음 날 시가</td><td>40</td><td>−1.11%</td><td>−2.01%</td><td>32%</td></tr>"
         "<tr><td>B 공모 부진 후 시장 반등</td><td>14</td><td>+6.89%</td><td>−1.06%</td><td>50%</td></tr>"
         "<tr><td>C 보호예수 해제 후 안정</td><td>52</td><td>−3.09%</td><td>−11.95%</td><td>31%</td></tr></tbody></table>"
         "<p class=muted>B는 14건뿐이라 결론을 낼 수 없고, 평균과 중앙값 차이가 커서 몇 종목이 끌어올린 숫자입니다. 규칙 숫자는 결과를 보기 전에 고정했습니다. 검증 구간은 열지 않았고, 표본이 작아 유의성 검정은 하지 않았습니다.</p>"
         "<p>자세한 표는 위 메뉴의 기초 통계·전략 A·B·C 페이지에 있습니다.</p>", dark=True),
    band("한계와 다음 단계",
         cards([("한계", "표본이 작습니다 (학습 142종목) · 보호예수 해제 일정을 모아 오지 못했습니다 · 상장 예정일은 사람이 직접 입력합니다"),
                ("다음 단계", "2026-11-16부터 모의 운영(앞으로의 데이터) · 검증 구간은 마지막에 한 번만 확인 · 조건 변경은 새 버전 설정 파일로 기록")], 2)
         + "<p>직접 돌려 보려면 <a href=local.html>직접 실행하기</a>를 보세요. 종목별 시세는 약관상 서로 줄 수 없어서 각자 자기 키로 모아야 합니다.</p>"),
]
INDEX = '<header class="hero"><p class=eyebrow>KOSDAQ IPO · 모의투자 연구</p><h1>IPO 전략 실험실</h1><p>조건을 바꿔 가며 “과거에 이렇게 샀다면?”을 시험해 보는 웹 앱 — 투자 경험이 없어도 이해할 수 있게 설명합니다. 실제 매매 권유가 아닙니다.</p></header>' + "\n".join(INTRO_BANDS)

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
