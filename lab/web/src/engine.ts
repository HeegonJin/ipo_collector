// lab/engine.py · lab/guards.py 를 브라우저에서 그대로 돌리기 위한 이식 (서버 없는 정적 사이트용).
// 숫자 계산은 파이썬과 같아야 한다 — tools/ 의 비교 스크립트와 tests/test_lab_static_parity.py 가 같은 값을 내는지 본다.
import type { Condition } from "./api";

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Row = Record<string, any>;
export type Costs = { commission_per_side: number; slippage_per_side: number; kosdaq_sell_tax: Record<string, number> };
export type Cfg = { min_n: number; confirm_phrase: string; trials_warn_at: number };
export type Eff = { entry: string; hold: number; conditions: Record<string, [number, number]> };
export type RawParams = { entry: string; hold: number; conditions: Record<string, { enabled: boolean; lo: number; hi: number }> };
export type Summary = { n: number; mean?: number; median?: number; win_rate?: number; avg_win?: number; avg_loss?: number;
  worst?: number; p10?: number; se?: number | null };

export const HOLDS = [1, 3, 5];
export const ENTRIES: Record<string, { label: string; in_design: boolean }> = {
  d0_close: { label: "상장일 종가 매수", in_design: true },
  d1_open: { label: "다음 거래일 시가 매수", in_design: false },
};

export class Engine {
  byId: Record<string, Condition>;
  constructor(public conditions: Condition[], public rows: Row[], public costs: Costs, public cfg: Cfg) {
    this.byId = Object.fromEntries(conditions.map((c) => [c.id, c]));
  }

  normalize(p: RawParams): Eff {
    if (!(p.entry in ENTRIES)) throw new Error(`알 수 없는 진입 시점: ${p.entry}`);
    if (!HOLDS.includes(p.hold)) throw new Error(`보유 기간은 ${HOLDS.join(",")} 중 하나여야 함: ${p.hold}`);
    const conds: Record<string, [number, number]> = {};
    for (const cid of Object.keys(p.conditions ?? {}).sort()) {
      const c = p.conditions[cid];
      const meta = this.byId[cid];
      if (!meta) throw new Error(`알 수 없는 조건: ${cid}`);
      if (!c.enabled) continue;
      const lo = Number(c.lo), hi = Number(c.hi);
      if (lo > hi) throw new Error(`${cid}: 하한이 상한보다 큼 (${lo} > ${hi})`);
      if (lo < meta.min || hi > meta.max) throw new Error(`${cid}: 범위 밖 (${meta.min}~${meta.max})`);
      conds[cid] = [lo, hi];
    }
    return { entry: p.entry, hold: Math.trunc(p.hold), conditions: conds };
  }

  private select(rows: Row[], eff: Eff) {
    const kept: Row[] = [];
    const unknown: Record<string, number> = {};
    for (const r of rows) {
      let ok = true;
      for (const [cid, [lo, hi]] of Object.entries(eff.conditions)) {
        const v = r[cid];
        if (v === null || v === undefined) { unknown[cid] = (unknown[cid] ?? 0) + 1; ok = false; break; }
        if (!(lo <= v && v <= hi)) { ok = false; break; }
      }
      if (ok) kept.push(r);
    }
    return { kept, unknown };
  }

  private trades(rows: Row[], eff: Eff) {
    const out: { ipo_id: string; name: string; list_date: string; net_ret: number }[] = [];
    let noExit = 0;
    const k = String(eff.hold);
    for (const r of rows) {
      const [entryPx, exitPx] = eff.entry === "d0_close" ? [r.close_d0, r.open_d[k]] : [r.open_d["1"], r.open_d[String(1 + eff.hold)]];
      if (!entryPx || !exitPx) { noExit++; continue; }
      const year = r.list_date.slice(0, 4);
      const tax = this.costs.kosdaq_sell_tax[year];
      if (tax === undefined) throw new Error(`매도세율이 없는 연도: ${year}`);
      const fee = this.costs.commission_per_side, slip = this.costs.slippage_per_side;
      out.push({ ipo_id: r.ipo_id, name: r.name, list_date: r.list_date,
        net_ret: (exitPx * (1 - fee - slip - tax)) / (entryPx * (1 + fee + slip)) - 1 });
    }
    return { trades: out, noExit };
  }

  // eff 는 normalize() 를 거친 정규형이다 (잘못된 파라미터는 normalize 에서 예외)
  evaluate(eff: Eff, split: string) {
    const pool = this.rows.filter((r) => r.split === split);
    const fillable = pool.filter((r) => !r.limit_up);
    const { kept, unknown } = this.select(fillable, eff);
    const { trades, noExit } = this.trades(kept, eff);
    const base = this.trades(fillable, { ...eff, conditions: {} }).trades;
    const unkTotal = Object.values(unknown).reduce((a, b) => a + b, 0);
    return {
      params: eff, split, trades,
      stats: summarize(trades.map((t) => t.net_ret)), baseline: summarize(base.map((t) => t.net_ret)),
      excluded: { limit_up: pool.length - fillable.length, no_exit_price: noExit, ...(unkTotal ? { unknown_value: unkTotal } : {}), ...unknown },
      lookahead: eff.entry === "d0_close" && Object.keys(eff.conditions).some((c) => this.byId[c].phase === "d0"),
      pool: pool.length,
    };
  }

  designExternal(eff: Eff): string[] {
    const out = Object.keys(eff.conditions).filter((c) => !this.byId[c].in_design);
    if (!ENTRIES[eff.entry].in_design) out.push(eff.entry);
    return out;
  }

  robustness(p: RawParams, split: string) {
    const eff = this.normalize(p);
    const minN = this.cfg.min_n;
    const center = this.evaluate(eff, split).stats;
    const out: { label: string; n: number; mean: number | null }[] = [];
    for (const [label, variant] of this.neighbors(eff)) {
      const s = this.evaluate(variant, split).stats;
      const ok = (s.n ?? 0) >= minN;
      out.push({ label, n: s.n ?? 0, mean: ok ? (s.mean as number) : null });
    }
    const valid = out.map((n) => n.mean).filter((m): m is number => m !== null);
    if ((center.n ?? 0) < minN || !valid.length) return { verdict: "판단 불가" as const, neighbors: out, flip_share: null };
    const c = center.mean as number;
    const flip = valid.filter((m) => m * c < 0).length / valid.length;
    const mx = Math.max(...valid);
    const spiky = c > mx && c - mx > (center.se ?? 0);
    return { verdict: (flip > 0.25 || spiky ? "취약" : "견고") as "취약" | "견고", neighbors: out, flip_share: flip };
  }

  private *neighbors(eff: Eff): Generator<[string, Eff]> {
    for (const [cid, [lo, hi]] of Object.entries(eff.conditions)) {
      const meta = this.byId[cid];
      const s = meta.step;
      const variants: [string, number, number][] = [[`${meta.label} 하한 −${s}`, lo - s, hi], [`${meta.label} 하한 +${s}`, lo + s, hi],
        [`${meta.label} 상한 −${s}`, lo, hi - s], [`${meta.label} 상한 +${s}`, lo, hi + s]];
      for (const [label, nl, nh] of variants) {
        if (nl > nh || nl < meta.min || nh > meta.max) continue;
        yield [label, { ...eff, conditions: { ...eff.conditions, [cid]: [nl, nh] } }];
      }
    }
    const i = HOLDS.indexOf(eff.hold);
    for (const j of [i - 1, i + 1]) if (j >= 0 && j < HOLDS.length) yield [`보유기간 ${HOLDS[j]}일`, { ...eff, hold: HOLDS[j] }];
  }
}

export function percentile(vals: number[], q: number): number {
  const s = [...vals].sort((a, b) => a - b);
  const pos = (s.length - 1) * q;
  const lo = Math.trunc(pos);
  const hi = Math.min(lo + 1, s.length - 1);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}

const mean = (v: number[]) => v.reduce((a, b) => a + b, 0) / v.length;

export function summarize(vals: number[]): Summary {
  if (!vals.length) return { n: 0 };
  const wins = vals.filter((v) => v > 0), losses = vals.filter((v) => v <= 0);
  const s = [...vals].sort((a, b) => a - b);
  const mid = s.length >> 1;
  const m = mean(vals);
  const se = vals.length > 1 ? Math.sqrt(vals.reduce((a, v) => a + (v - m) ** 2, 0) / (vals.length - 1)) / Math.sqrt(vals.length) : null;
  return { n: vals.length, mean: m, median: s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2, win_rate: wins.length / vals.length,
    avg_win: wins.length ? mean(wins) : 0, avg_loss: losses.length ? mean(losses) : 0, worst: s[0], p10: percentile(vals, 0.1), se };
}

export function mask(stats: Summary, minN: number) {
  const n = stats.n ?? 0;
  if (n < minN) return { n, insufficient: true as const, min_n: minN };
  return { ...stats, insufficient: false as const } as any;
}

export const chanceBest = (n: number, se: number | null | undefined) => (!se || n < 2 ? 0 : se * Math.sqrt(2 * Math.log(n)));

// 같은 조합을 같은 해시로 세기 위한 정규형 해시 (파이썬의 sha1 과 값은 다르지만 일관되면 충분하다)
export function paramsHash(eff: Eff): string {
  const canon = JSON.stringify({ conditions: Object.fromEntries(Object.entries(eff.conditions).sort()), entry: eff.entry, hold: eff.hold });
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  for (let i = 0; i < canon.length; i++) {
    const ch = canon.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16).padStart(10, "0").slice(0, 10);
}
