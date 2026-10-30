import { useEffect, useMemo, useRef, useState } from "react";
import { api, Condition, EvalResult, Meta, Neighbor, Params, Stats, ValidResult } from "./api";

const pct = (v: number | null | undefined, d = 2) => (v == null ? "-" : `${(v * 100).toFixed(d)}%`);
const fmt = (v: number, step: number) => (step >= 1 ? v.toFixed(0) : v.toFixed(step < 0.1 ? 2 : 2).replace(/\.?0+$/, ""));

function initialParams(meta: Meta): Params {
  return {
    entry: "d0_close", hold: 1,
    conditions: Object.fromEntries(meta.conditions.map((c) => [c.id, { enabled: false, lo: c.min, hi: c.max }])),
  };
}

function Badge({ kind, children }: { kind: "warn" | "info" | "ok"; children: React.ReactNode }) {
  return <span className={`badge ${kind}`}>{children}</span>;
}

function ConditionRow({ c, state, onChange }: {
  c: Condition; state: Params["conditions"][string]; onChange: (s: Params["conditions"][string]) => void;
}) {
  const set = (p: Partial<typeof state>) => onChange({ ...state, ...p });
  return (
    <div className={`cond ${state.enabled ? "on" : ""}`}>
      <label className="cond-head">
        <input type="checkbox" checked={state.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
        <span className="cond-title">{c.label}</span>
        {c.phase === "d0" ? <Badge kind="warn">상장일 마감 후 값</Badge> : <Badge kind="ok">상장 전 확정</Badge>}
        {!c.in_design && <Badge kind="info">설계도 외 탐색</Badge>}
      </label>
      <div className="hint">{c.hint}</div>
      {state.enabled && (
        <div className="range">
          {(["lo", "hi"] as const).map((k) => (
            <label key={k}>
              <span>{k === "lo" ? "하한" : "상한"} <b>{fmt(state[k], c.step)}{c.unit}</b></span>
              <input type="range" min={c.min} max={c.max} step={c.step} value={state[k]}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  set(k === "lo" ? { lo: Math.min(v, state.hi) } : { hi: Math.max(v, state.lo) });
                }} />
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function StatsTable({ rows }: { rows: { name: string; s: Stats }[] }) {
  return (
    <table>
      <thead><tr><th>구분</th><th>건수</th><th>평균</th><th>중앙값</th><th>승률</th><th>평균 이익 / 손실</th><th>하위 10%</th><th>최악</th></tr></thead>
      <tbody>
        {rows.map(({ name, s }) => s.insufficient ? (
          <tr key={name}><td>{name}</td><td>{s.n}</td><td colSpan={6} className="muted">표본 {s.min_n}건 미만 — 숫자를 보여주지 않습니다</td></tr>
        ) : (
          <tr key={name}><td>{name}</td><td>{s.n}</td><td>{pct(s.mean)}</td><td>{pct(s.median)}</td>
            <td>{(s.win_rate * 100).toFixed(1)}%</td><td>{pct(s.avg_win)} / {pct(s.avg_loss)}</td><td>{pct(s.p10)}</td><td>{pct(s.worst)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function Histogram({ values }: { values: number[] }) {
  if (!values.length) return null;
  const lo = Math.floor(Math.min(...values, 0) * 20) / 20, hi = Math.ceil(Math.max(...values, 0) * 20) / 20;
  const bins = Math.max(1, Math.round((hi - lo) / 0.05));
  const counts = new Array(bins).fill(0);
  values.forEach((v) => counts[Math.min(bins - 1, Math.floor((v - lo) / 0.05))]++);
  const W = 560, H = 120, bw = W / bins, max = Math.max(...counts);
  const zero = ((0 - lo) / (hi - lo || 1)) * W;
  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} role="img" aria-label="거래별 순수익률 분포" className="hist">
      {counts.map((n, i) => {
        const x0 = lo + i * 0.05;
        return <rect key={i} x={i * bw + 1} y={H - (n / max) * H} width={bw - 2} height={(n / max) * H}
          className={x0 >= 0 ? "bar-pos" : "bar-neg"}><title>{pct(x0, 0)}~{pct(x0 + 0.05, 0)}: {n}건</title></rect>;
      })}
      <line x1={zero} x2={zero} y1={0} y2={H} className="zero" />
      <text x={0} y={H + 14} className="axis">{pct(lo, 0)}</text>
      <text x={W} y={H + 14} textAnchor="end" className="axis">{pct(hi, 0)}</text>
    </svg>
  );
}

function Robustness({ r }: { r: EvalResult["robustness"] }) {
  const kind = r.verdict === "견고" ? "ok" : r.verdict === "취약" ? "warn" : "info";
  return (
    <section>
      <h3>이웃 구간 견고성 <Badge kind={kind}>{r.verdict}</Badge></h3>
      <p className="muted">기준값을 한 칸씩 옮기거나 보유기간을 바꿔도 결과가 비슷한지 봅니다. 한 점에서만 좋으면 우연일 가능성이 큽니다.</p>
      <table><thead><tr><th>변형</th><th>건수</th><th>평균</th></tr></thead>
        <tbody>{r.neighbors.map((n: Neighbor) => (
          <tr key={n.label}><td>{n.label}</td><td>{n.n}</td><td>{n.mean == null ? <span className="muted">표본 부족</span> : pct(n.mean)}</td></tr>
        ))}</tbody></table>
    </section>
  );
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [params, setParams] = useState<Params | null>(null);
  const [count, setCount] = useState<number | null>(null);
  const [result, setResult] = useState<EvalResult | null>(null);
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [yaml, setYaml] = useState("");
  const [phrase, setPhrase] = useState("");
  const [valid, setValid] = useState<ValidResult | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    api.meta().then((m) => { setMeta(m); setParams(initialParams(m)); })
      .catch((e) => setError(`서버에 연결할 수 없습니다: ${e.message} — python -m lab.server <날짜> 를 실행했는지 확인하세요`));
  }, []);

  // 건수는 슬라이더를 움직이는 대로 갱신하지만(시도로 세지 않음), 수익률은 '실행'을 눌러야 계산한다
  useEffect(() => {
    if (!params) return;
    const id = ++seq.current;
    const t = setTimeout(() => {
      api.count(params).then((c) => { if (id === seq.current) setCount(c.n); }).catch(() => undefined);
    }, 200);
    if (result) setStale(true);
    setValid(null);
    return () => clearTimeout(t);
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  const trades = result?.trades.map((t) => t.net_ret) ?? [];
  const best = useMemo(() => [...(result?.trades ?? [])].sort((a, b) => b.net_ret - a.net_ret).slice(0, 3), [result]);

  if (!meta || !params) return <main><h1>IPO 전략 실험실</h1>{error ? <p className="err">{error}</p> : <p>불러오는 중…</p>}</main>;

  const run = async () => {
    setBusy(true); setError("");
    try { setResult(await api.evaluate(params)); setStale(false); setYaml(""); }
    catch (e) { setError((e as Error).message); }
    setBusy(false);
  };
  const openValid = async () => {
    setBusy(true); setError("");
    try { setValid(await api.validate(params, phrase)); }
    catch (e) { setError((e as Error).message); }
    setBusy(false);
  };
  const tooFew = count != null && count < meta.min_n;

  return (
    <main>
      <header>
        <h1>IPO 전략 실험실</h1>
        <p className="muted">학습 구간 {meta.split_sizes.train}종목 · 검증 구간 {meta.split_sizes.valid}종목은 잠겨 있습니다 · 모의투자 전용, 비용 차감 후 수익률</p>
      </header>
      {error && <p className="err" role="alert">{error}</p>}
      <div className="grid">
        <aside>
          <h2>진입 · 보유</h2>
          <fieldset>
            <legend>진입 시점</legend>
            {Object.entries(meta.entries).map(([id, e]) => (
              <label key={id} className="radio">
                <input type="radio" name="entry" checked={params.entry === id} onChange={() => setParams({ ...params, entry: id })} />
                {e.label} {!e.in_design && <Badge kind="info">설계도 외 탐색</Badge>}
              </label>
            ))}
          </fieldset>
          <fieldset>
            <legend>보유 기간 (진입일부터 N거래일 뒤 시가 매도)</legend>
            {meta.holds.map((h) => (
              <label key={h} className="radio">
                <input type="radio" name="hold" checked={params.hold === h} onChange={() => setParams({ ...params, hold: h })} />D+{h}
              </label>
            ))}
          </fieldset>
          <h2>종목 조건</h2>
          {meta.conditions.map((c) => (
            <ConditionRow key={c.id} c={c} state={params.conditions[c.id]}
              onChange={(s) => setParams({ ...params, conditions: { ...params.conditions, [c.id]: s } })} />
          ))}
          <div className="runbar">
            <div>조건에 맞는 거래 <b>{count ?? "…"}</b>건{tooFew && <span className="warn-text"> (최소 {meta.min_n}건 미만 → 결과 숨김)</span>}</div>
            <button onClick={run} disabled={busy} className="primary">{busy ? "계산 중…" : "실행 (학습 구간)"}</button>
          </div>
        </aside>

        <section className="results">
          {!result ? <p className="muted">조건을 고르고 ‘실행’을 누르세요. 실행할 때마다 서로 다른 조합은 시도 횟수로 기록됩니다.</p> : (
            <>
              {stale && <p className="stale">조건이 바뀌었습니다. 아래 결과는 이전 실행 기준입니다.</p>}
              <div className="banners">
                {result.lookahead && <p className="banner warn">상장일 마감 후 값 + 상장일 종가 진입: 15:20 시점엔 알 수 없는 정보를 쓴 <b>상한 추정</b>입니다. 실제 매매에서는 이만큼 나오지 않습니다. ‘다음 거래일 시가 매수’로 바꿔 비교해 보세요.</p>}
                {result.design_external.length > 0 && <p className="banner info">설계도 밖 조건 사용: {result.design_external.join(", ")} — 탐색 결과이며 설계 문서의 근거가 없습니다.</p>}
                <p className={`banner ${result.trials.warn ? "warn" : "info"}`}>
                  지금까지 서로 다른 조합 <b>{result.trials.distinct}개</b>를 봤습니다.
                  {result.trials.distinct >= 2 && <> 이 정도 시도면 아무 효과가 없어도 최고 평균이 우연히 <b>약 {pct(result.trials.chance_best)}</b>까지 나올 수 있습니다 — 이 값을 넘지 못하면 믿지 마세요.</>}
                  {result.trials.warn && ` (경고 기준 ${result.trials.warn_at}개 초과)`}
                </p>
              </div>
              <h3>학습 구간 결과</h3>
              <StatsTable rows={[{ name: "내 조건", s: result.stats }, { name: "기준선(조건 없음)", s: result.baseline }]} />
              <p className="muted small">제외: 상한가 종가 {result.excluded.limit_up ?? 0}건 · 청산가 없음 {result.excluded.no_exit_price ?? 0}건
                {result.excluded.unknown_value ? ` · 값을 몰라 제외 ${result.excluded.unknown_value}건` : ""} · 구간 전체 {result.pool}건</p>
              {!result.stats.insufficient && <><Histogram values={trades} />
                <p className="muted small">가장 높았던 3건: {best.map((t) => `${t.name} ${pct(t.net_ret, 1)}`).join(" · ")} — 몇 종목이 평균을 끌고 가는지 확인하세요.</p></>}
              <Robustness r={result.robustness} />

              <section>
                <h3>검증 구간 열기</h3>
                <p className="muted">검증 구간은 <b>마지막에 한 번</b> 확인하는 용도입니다. 열 때마다 기록되고 두 번째부터 경고가 붙습니다. 학습 구간에서 실행한 조건만 열 수 있습니다.</p>
                <div className="valid-row">
                  <input value={phrase} onChange={(e) => setPhrase(e.target.value)} placeholder={`“${meta.confirm_phrase}” 를 그대로 입력`} aria-label="확인 문구" />
                  <button onClick={openValid} disabled={busy || phrase !== meta.confirm_phrase || stale}>검증 구간 열기</button>
                </div>
                {valid && (
                  <div>
                    {valid.warning && <p className="banner warn">{valid.warning}</p>}
                    <StatsTable rows={[{ name: "검증: 내 조건", s: valid.stats }, { name: "검증: 기준선", s: valid.baseline }]} />
                  </div>
                )}
              </section>

              <section>
                <h3>내보내기</h3>
                <button onClick={async () => setYaml((await api.exportYaml(params)).yaml)} disabled={stale}>YAML 초안 보기</button>
                {yaml && <pre>{yaml}</pre>}
              </section>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
