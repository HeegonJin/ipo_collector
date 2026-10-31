import { useCallback, useEffect, useState } from "react";
import { LedgerItem, opsApi, ReportRow, RunResult, ScheduleEntry } from "./api";

const pct = (v: number | null | undefined) => (v == null ? "-" : `${(v * 100).toFixed(2)}%`);
const today = () => { const d = new Date(); return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`; };
const JOBS = [
  { cmd: "swing", label: "전략 B·C 판단", when: "매일 08:30~08:35 (전 거래일 KRX 수집 후)" },
  { cmd: "a0", label: "A0 판단 (오늘 상장 종목)", when: "상장일 15:20~15:25" },
  { cmd: "settle", label: "정산", when: "저녁, 수집된 마지막 날짜로" },
];

function ReportTable({ rows }: { rows: ReportRow[] }) {
  if (!rows.length) return <p className="muted">대상 없음</p>;
  return (
    <table><thead><tr><th>전략</th><th>종목</th><th>판단</th><th>장부</th><th>이유</th></tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={i}><td>{r.strategy}</td><td>{r.name}</td><td>{r.action}</td>
          <td>{r.recorded ? "기록" : "미기록"}{r.late && <span className="warn-text"> 무효(늦음)</span>}</td>
          <td style={{ textAlign: "left" }}>{r.reasons.join("; ")}</td></tr>
      ))}</tbody></table>
  );
}

export default function Ops() {
  const [entries, setEntries] = useState<ScheduleEntry[]>([]);
  const [regError, setRegError] = useState("");
  const [items, setItems] = useState<LedgerItem[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ list_date: "", corp_name: "", stock_code: "", offer_price: "" });
  const [day, setDay] = useState(today());
  const [allowStale, setAllowStale] = useState(false);
  const [last, setLast] = useState<RunResult | null>(null);

  const reload = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([opsApi.schedule(), opsApi.ledger()]);
      setEntries(s.entries); setRegError(s.registry_error); setItems(l.items); setProblems(l.problems);
    } catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  const add = async () => {
    setBusy(true); setError(""); setNote("");
    try {
      const r = await opsApi.addSchedule(form);
      setNote(r.late ? "추가했지만 상장일 15:20 이후라 오늘 판단에는 쓰이지 않습니다." : `추가: ${r.entry.corp_name}`);
      setForm({ list_date: "", corp_name: "", stock_code: "", offer_price: "" });
      await reload();
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  };
  const run = async (cmd: string, label: string) => {
    if (!window.confirm(`${label}을(를) ${day} 기준으로 지금 실행합니다. 판단 시각 +5분이 지났으면 장부에 무효로 남고, 장부는 지울 수 없습니다. 계속할까요?`)) return;
    setBusy(true); setError(""); setLast(null);
    try { setLast(await opsApi.run(cmd, day, allowStale)); await reload(); }
    catch (e) { setError((e as Error).message); }
    setBusy(false);
  };

  return (
    <div className="ops">
      {error && <p className="err" role="alert">{error}</p>}
      {note && <p className="banner info">{note}</p>}

      <section className="panel">
        <h2>상장 일정 (수기 입력)</h2>
        <p className="muted">무료로 상장 예정일을 얻을 출처가 없어 사람이 직접 적습니다. 입력한 시각 이후부터 판단에 쓰이며, 회사명은 DART 표기와 같아야 연결됩니다.</p>
        <div className="form-row">
          <input placeholder="상장일 YYYYMMDD" value={form.list_date} onChange={(e) => setForm({ ...form, list_date: e.target.value })} aria-label="상장일" />
          <input placeholder="회사명" value={form.corp_name} onChange={(e) => setForm({ ...form, corp_name: e.target.value })} aria-label="회사명" />
          <input placeholder="종목코드 6자리" value={form.stock_code} onChange={(e) => setForm({ ...form, stock_code: e.target.value })} aria-label="종목코드" />
          <input placeholder="공모가(선택)" value={form.offer_price} onChange={(e) => setForm({ ...form, offer_price: e.target.value })} aria-label="공모가" />
          <button className="primary" onClick={add} disabled={busy || !form.list_date || !form.corp_name || !form.stock_code}>추가</button>
        </div>
        {regError && <p className="warn-text">{regError}</p>}
        {entries.length === 0 ? <p className="muted">입력된 일정이 없습니다.</p> : (
          <table><thead><tr><th>상장일</th><th>회사</th><th>코드</th><th>공모가</th><th>DART 연결</th></tr></thead>
            <tbody>{entries.map((e) => (
              <tr key={e.list_date + e.stock_code}><td>{e.list_date}</td><td>{e.corp_name}</td><td>{e.stock_code}</td>
                <td>{e.offer_price ?? "-"}</td><td>{e.ipo_id ? "연결됨" : <span className="warn-text">못 찾음 (관망으로 기록)</span>}</td></tr>
            ))}</tbody></table>
        )}
      </section>

      <section className="panel">
        <h2>일일 판단 작업</h2>
        <div className="form-row">
          <label>기준 날짜 <input value={day} onChange={(e) => setDay(e.target.value)} aria-label="기준 날짜" /></label>
          <label className="radio"><input type="checkbox" checked={allowStale} onChange={(e) => setAllowStale(e.target.checked)} />B·C: 전 거래일 자료 없어도 실행(휴장일)</label>
        </div>
        <div className="jobs">
          {JOBS.map((j) => (
            <div key={j.cmd} className="job">
              <button onClick={() => run(j.cmd, j.label)} disabled={busy}>{j.label}</button>
              <span className="muted small">{j.when}</span>
            </div>
          ))}
        </div>
        {last?.report && <ReportTable rows={last.report} />}
        {last?.result && (
          <p className="banner info">정산 {last.result.settled}건 추가 · 무결성 문제 {last.result.problems.length ? last.result.problems.join(" / ") : "없음"}
            {last.result.missing_bars.length > 0 && <span className="warn-text"> · 상장일 시세 없음(코드 오입력 의심): {last.result.missing_bars.join(", ")}</span>}</p>
        )}
      </section>

      <section className="panel">
        <h2>모의 장부 <span className="muted small">추가만 가능 · 해시 체인</span></h2>
        {problems.length > 0 && <p className="err">장부 무결성 문제: {problems.join(" / ")}</p>}
        {items.length === 0 ? <p className="muted">기록된 판단이 없습니다.</p> : (
          <table><thead><tr><th>판단 시각</th><th>전략</th><th>종목</th><th>판단</th><th>유효</th><th>청산</th><th>순수익률</th></tr></thead>
            <tbody>{items.map((it, i) => (
              <tr key={i}><td>{it.as_of.slice(0, 16).replace("T", " ")}</td><td>{it.strategy}</td><td>{it.short_code ?? it.ipo_id}</td>
                <td title={it.reasons.join("; ")}>{it.action}</td>
                <td>{it.valid ? "유효" : <span className="warn-text" title={it.invalid_reason ?? ""}>무효</span>}</td>
                <td>{it.settled ? `${it.exit_kind}${it.exit_reason ? ` · ${it.exit_reason}` : ""}${it.exit_date ? ` ${it.exit_date}` : ""}` : "대기"}</td>
                <td>{pct(it.net_ret)}</td></tr>
            ))}</tbody></table>
        )}
      </section>
    </div>
  );
}
