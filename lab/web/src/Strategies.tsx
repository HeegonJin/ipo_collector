import { useEffect, useState } from "react";
import { BacktestResult, MaskedStats, PitCard, strategyApi, StrategyInfo } from "./api";

const pct = (v: number | null | undefined, d = 2) => (v == null ? "-" : `${(v * 100).toFixed(d)}%`);

function StatRows({ rows }: { rows: { name: string; s: MaskedStats }[] }) {
  return (
    <table>
      <thead><tr><th>구분</th><th>건수</th><th>평균</th><th>중앙값</th><th>승률</th><th>평균 이익 / 손실</th><th>하위 10%</th><th>최악</th></tr></thead>
      <tbody>{rows.map(({ name, s }) => s.insufficient ? (
        <tr key={name}><td>{name}</td><td>{s.n}</td><td colSpan={6} className="muted">표본 {s.min_n}건 미만 — 숫자를 보여주지 않습니다</td></tr>
      ) : (
        <tr key={name}><td>{name}</td><td>{s.n}</td><td>{pct(s.mean)}</td><td>{pct(s.median)}</td><td>{(s.win_rate * 100).toFixed(1)}%</td>
          <td>{pct(s.avg_win)} / {pct(s.avg_loss)}</td><td>{pct(s.p10)}</td><td>{pct(s.worst)}</td></tr>
      ))}</tbody>
    </table>
  );
}

function Backtest() {
  const [cat, setCat] = useState<StrategyInfo[]>([]);
  const [sid, setSid] = useState("A0");
  const [ov, setOv] = useState<Record<string, number>>({});
  const [res, setRes] = useState<BacktestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { strategyApi.catalog().then((c) => setCat(c.strategies)).catch((e) => setErr(String(e.message))); }, []);
  const cur = cat.find((s) => s.id === sid);
  const run = async () => {
    setBusy(true); setErr("");
    try { setRes(await strategyApi.run(sid, ov)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const download = () => {
    if (!res) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([res.doc], { type: "text/markdown" }));
    a.download = `${res.strategy}_train${res.exploratory ? "_탐색" : ""}.md`; a.click();
  };
  return (
    <div className="grid">
      <aside>
        <h2>전략 규칙</h2>
        <p className="muted small">팀이 고정한 규칙(config/strategy_*_v1.yaml)을 판단 코드로 날짜마다 돌립니다. 모의 운영과 같은 코드입니다.</p>
        {cat.map((s) => (
          <label key={s.id} className="radio">
            <input type="radio" name="strategy" checked={sid === s.id} onChange={() => { setSid(s.id); setOv({}); setRes(null); }} />{s.label}
          </label>
        ))}
        {cur && cur.knobs.length > 0 && (<>
          <h2>규칙 숫자 바꿔 보기 <span className="badge info">탐색</span></h2>
          <p className="muted small">바꾸면 ‘탐색’으로 표시되고 시도 횟수에 더해집니다. 학습 구간에서만 돌립니다.</p>
          {cur.knobs.map((k) => {
            const v = ov[k.path] ?? k.default;
            return (
              <label key={k.path} className="cond" style={{ display: "grid" }}>
                <span className="cond-title">{k.label}: <b>{v}</b>{v !== k.default && <span className="warn-text"> (기본 {k.default})</span>}</span>
                <input type="range" min={k.min} max={k.max} step={k.step} value={v}
                  onChange={(e) => { const n = Number(e.target.value); const o = { ...ov }; if (n === k.default) delete o[k.path]; else o[k.path] = n; setOv(o); }} />
              </label>
            );
          })}
        </>)}
        <div className="runbar"><button className="primary" onClick={run} disabled={busy}>{busy ? "계산 중…" : "백테스트 실행 (학습 구간)"}</button></div>
      </aside>
      <section className="results">
        {err && <p className="err" role="alert">{err}</p>}
        {!res ? <p className="muted">전략을 고르고 실행하세요. 검증 구간은 ‘전략 실험’ 탭의 잠금으로만 엽니다.</p> : (<>
          <div className="banners">
            {res.exploratory && <p className="banner warn">규칙 숫자를 바꾼 <b>탐색</b> 결과입니다 ({Object.entries(res.overrides).map(([k, v]) => `${k}=${v}`).join(", ")}). 서로 다른 시도 {res.trials.distinct}개 — 우연 최고치 약 <b>{pct(res.trials.chance_best)}</b>를 넘지 못하면 믿지 마세요.</p>}
            {!res.exploratory && <p className="banner info">팀이 결과를 보기 전에 고정한 규칙 {res.version} 그대로입니다.</p>}
            {res.concentration.verdict === "쏠림 의심" && <p className="banner warn">상위 2건을 빼면 평균이 {pct(res.concentration.mean_without_top)}로 내려갑니다 — 한두 종목에 쏠린 결과라 보류 대상입니다 (설계 L8).</p>}
          </div>
          <h3>{res.label}</h3>
          <StatRows rows={[{ name: "이 전략", s: res.stats }, { name: "A0 기준선", s: res.baseline_a0 }, { name: "코스닥 대비 초과수익", s: res.excess_vs_kosdaq }]} />
          <p className="muted small">신호 {res.signals}건 · 체결 불확실(매수일 시세 없음) {res.no_fill}건 · 상한가 종가 제외 {res.limit_up_excluded}건 · 청산 대기 {res.pending}건
            · 청산 종류 {Object.entries(res.exit_kinds).map(([k, v]) => `${k} ${v}`).join(" / ")} · 쏠림 점검: {res.concentration.verdict}</p>
          <p className="muted small">비용: 수수료 편도 {(res.costs.commission_per_side * 100).toFixed(3)}% · 슬리피지 편도 {(res.costs.slippage_per_side * 100).toFixed(2)}% · 매도세 {Object.entries(res.costs.kosdaq_sell_tax).map(([y, t]) => `${y} ${(t * 100).toFixed(2)}%`).join(", ")} · 시세: KRX 통계정보</p>
          {Object.keys(res.by_reason).length > 0 && <StatRows rows={Object.entries(res.by_reason).map(([k, s]) => ({ name: `청산 사유: ${k}`, s }))} />}
          {res.trades.length > 0 && (
            <details><summary>거래 {res.trades.length}건</summary>
              <table><thead><tr><th>종목</th><th>신호일</th><th>매수일</th><th>청산일</th><th>사유</th><th>순수익</th><th>코스닥</th></tr></thead>
                <tbody>{res.trades.map((t, i) => (<tr key={i}><td>{t.name}</td><td>{t.signal_date}</td><td>{t.entry_date}</td><td>{t.exit_date ?? "-"}</td><td>{t.reason ?? "-"}</td><td>{pct(t.net_ret)}</td><td>{pct(t.bench_ret)}</td></tr>))}</tbody></table>
            </details>)}
          <p><button onClick={download}>결과 문서(.md) 받기</button> <span className="muted small">results/README 형식: 기간·비용·체결 가정·평균/중앙값/승률/손익비/최악·기준선</span></p>
        </>)}
      </section>
    </div>
  );
}

function Pit() {
  const [ipos, setIpos] = useState<{ ipo_id: string; name: string; list_date: string; split: string }[]>([]);
  const [ipo, setIpo] = useState("");
  const [asOf, setAsOf] = useState("");
  const [card, setCard] = useState<PitCard | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { strategyApi.ipos().then((r) => { setIpos(r.ipos); }).catch((e) => setErr(e.message)); }, []);
  const pick = (id: string) => {
    setIpo(id); const r = ipos.find((i) => i.ipo_id === id);
    if (r) setAsOf(`${r.list_date.slice(0, 4)}-${r.list_date.slice(4, 6)}-${r.list_date.slice(6)}T15:20`);
  };
  const go = async () => { setErr(""); try { setCard(await strategyApi.card(ipo, `${asOf}:00+09:00`)); } catch (e) { setErr((e as Error).message); } };
  const rows = (fs: PitCard["visible"]) => fs.map((f, i) => (<tr key={i}><td>{f.var}</td><td>{String(f.value ?? "-")}</td><td>{f.status}</td><td>{f.available_at.slice(0, 16).replace("T", " ")}</td></tr>));
  return (
    <div className="ops">
      <div className="panel">
        <h2>PIT 카드 — 그 시각에 판단 코드가 볼 수 있는 값</h2>
        <p className="muted">종목과 판단 시각(as_of)을 고르면, 그 시각에 이미 공개된 값(공개 시각 ≤ as_of)과 아직 가려진 값, 그리고 A0·B·C가 그 시각에 내릴 판단을 보여줍니다. 백테스트와 모의 운영이 같은 규칙으로 값을 거릅니다.</p>
        <div className="form-row">
          <select value={ipo} onChange={(e) => pick(e.target.value)} aria-label="종목"><option value="">종목 선택</option>
            {ipos.map((i) => <option key={i.ipo_id} value={i.ipo_id}>{i.name} ({i.list_date}, {i.split})</option>)}</select>
          <input type="datetime-local" value={asOf} onChange={(e) => setAsOf(e.target.value)} aria-label="판단 시각" />
          <button className="primary" onClick={go} disabled={!ipo || !asOf}>보기</button>
        </div>
        {err && <p className="err" role="alert">{err}</p>}
      </div>
      {card && (<>
        <div className="panel"><h2>{card.name} · {card.as_of.slice(0, 16).replace("T", " ")} 판단</h2>
          <table><thead><tr><th>전략</th><th>판단</th><th>이유</th></tr></thead>
            <tbody>{card.signals.map((s) => (<tr key={s.strategy}><td>{s.strategy}</td><td>{s.action}</td><td style={{ textAlign: "left" }}>{s.reasons.join("; ")}</td></tr>))}</tbody></table>
          <p className="muted small">그 시각까지 보이는 일봉 {card.bars_visible}개 · {card.note}</p></div>
        <div className="panel"><h2>보이는 값 {card.visible.length}개</h2>
          <table><thead><tr><th>변수</th><th>값</th><th>상태</th><th>공개 시각</th></tr></thead><tbody>{rows(card.visible)}</tbody></table></div>
        <div className="panel"><h2>아직 가려진 값 {card.hidden.length}개 <span className="badge warn">읽으면 look-ahead</span></h2>
          {card.hidden.length ? <table><thead><tr><th>변수</th><th>값</th><th>상태</th><th>공개 시각</th></tr></thead><tbody>{rows(card.hidden)}</tbody></table> : <p className="muted">이 시각 이후에 공개되는 값이 없습니다.</p>}</div>
      </>)}
    </div>
  );
}

function Basic() {
  const [doc, setDoc] = useState<{ doc: string; file: string | null } | null>(null);
  useEffect(() => { strategyApi.basicStats().then(setDoc).catch(() => setDoc({ doc: "", file: null })); }, []);
  if (!doc) return <p className="muted">불러오는 중…</p>;
  if (!doc.file) return <p className="muted">기초 통계 문서가 없습니다. <code>python -m evaluate.basic_stats 20261030</code> 으로 만드세요.</p>;
  return <div className="panel"><p className="muted small">{doc.file} · 학습 구간 기술 통계 (설계 L8 첫 산출물: 경쟁률·규모·첫날 유형별 분포)</p><pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{doc.doc}</pre></div>;
}

export default function Strategies() {
  const [sub, setSub] = useState<"bt" | "pit" | "basic">("bt");
  const tabs: [typeof sub, string][] = [["bt", "전략 백테스트"], ["pit", "PIT 카드"], ["basic", "기초 통계"]];
  return (<>
    <nav className="tabs" role="tablist" aria-label="전략 백테스트 하위 메뉴">
      {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={sub === k} className={sub === k ? "active" : ""} onClick={() => setSub(k)}>{l}</button>)}
    </nav>
    {sub === "bt" ? <Backtest /> : sub === "pit" ? <Pit /> : <Basic />}
  </>);
}
