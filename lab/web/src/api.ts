export type Condition = {
  id: string; label: string; hint: string; phase: "pre" | "d0"; unit: string;
  min: number; max: number; step: number; in_design: boolean;
};
export type Meta = {
  conditions: Condition[];
  entries: Record<string, { label: string; in_design: boolean }>;
  holds: number[]; min_n: number; trials_warn_at: number; confirm_phrase: string;
  split_sizes: Record<string, number>; coverage: Record<string, number>; data_end?: string;
  splits?: Record<string, { start: string; end: string }>;
};
export type CondState = { enabled: boolean; lo: number; hi: number };
export type Params = { entry: string; hold: number; conditions: Record<string, CondState> };
export type Stats =
  | { n: number; insufficient: true; min_n: number }
  | { n: number; insufficient: false; mean: number; median: number; win_rate: number;
      avg_win: number; avg_loss: number; p10: number; worst: number; se: number | null };
export type Neighbor = { label: string; n: number; mean: number | null };
export type EvalResult = {
  split: string; hash: string; stats: Stats; baseline: Stats;
  excluded: Record<string, number>; lookahead: boolean; pool: number; design_external: string[];
  trades: { name: string; list_date: string; net_ret: number }[];
  robustness: { verdict: "견고" | "취약" | "판단 불가"; neighbors: Neighbor[]; flip_share: number | null };
  trials: { distinct: number; total: number; warn: boolean; warn_at: number; chance_best: number };
};
export type ValidResult = {
  split: string; hash: string; stats: Stats; baseline: Stats; excluded: Record<string, number>;
  lookahead: boolean; warning: string;
};

import { staticApi } from "./staticApi";

// 서버 없이 정적 사이트로 배포할 때는 `vite build --mode static` — 브라우저 안에서 계산한다 (staticApi.ts)
export const IS_STATIC = import.meta.env.MODE === "static";

async function request<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error ?? `요청 실패 (${res.status})`);
  return data as T;
}

const serverApi = {
  meta: () => request<Meta>("/api/meta"),
  count: (params: Params) => request<{ n: number; pool: number }>("/api/count", { params }),
  evaluate: (params: Params) => request<EvalResult>("/api/evaluate", { params }),
  validate: (params: Params, confirm: string) => request<ValidResult>("/api/validate", { params, confirm }),
  exportYaml: (params: Params) => request<{ yaml: string }>("/api/export", { params }),
};

export type ScheduleEntry = {
  list_date: string; corp_name: string; stock_code: string; offer_price: number | null; entered_at: string; ipo_id: string | null;
};
export type LedgerItem = {
  as_of: string; strategy: string; ipo_id: string; short_code: string | null; action: string; reasons: string[];
  valid: boolean; invalid_reason: string | null; settled: boolean; net_ret: number | null;
  exit_kind: string | null; exit_reason: string | null; exit_date: string | null;
};
export type ReportRow = { strategy: string; name: string; action: string; reasons: string[]; recorded: boolean; late?: boolean };
export type RunResult = {
  cmd: string; report?: ReportRow[];
  result?: { settled: number; problems: string[]; missing_bars: string[] };
};

export const opsApi = {
  schedule: () => request<{ entries: ScheduleEntry[]; registry_error: string }>("/api/ops/schedule"),
  addSchedule: (b: { list_date: string; corp_name: string; stock_code: string; offer_price?: string }) =>
    request<{ entry: ScheduleEntry; late: boolean }>("/api/ops/schedule/add", b),
  ledger: () => request<{ items: LedgerItem[]; problems: string[]; rows: number }>("/api/ops/ledger"),
  run: (cmd: string, day: string, allow_stale = false) => request<RunResult>("/api/ops/run", { cmd, day, allow_stale }),
};

export const api = IS_STATIC ? staticApi : serverApi;

export type Knob = { path: string; label: string; min: number; max: number; step: number; default: number };
export type StrategyInfo = { id: string; label: string; knobs: Knob[]; yaml: string | null };
export type MaskedStats =
  | { n: number; insufficient: true; min_n: number }
  | { n: number; insufficient: false; mean: number; median: number; win_rate: number; avg_win: number; avg_loss: number; p10: number; worst: number };
export type BacktestResult = {
  strategy: string; label: string; version: string; overrides: Record<string, number>; exploratory: boolean;
  signals: number; no_fill: number; pending: number; limit_up_excluded: number;
  stats: MaskedStats; baseline_a0: MaskedStats; excess_vs_kosdaq: MaskedStats;
  concentration: { verdict: string; mean_without_top: number | null };
  by_reason: Record<string, MaskedStats>; exit_kinds: Record<string, number>;
  trials: { distinct: number; chance_best: number; warn: boolean; warn_at: number };
  trades: { name: string; signal_date: string; entry_date: string; exit_date: string | null; reason: string | null; kind: string | null; net_ret: number; bench_ret: number | null }[];
  costs: { commission_per_side: number; slippage_per_side: number; kosdaq_sell_tax: Record<string, number> };
  doc: string;
};
export type PitFact = { var: string; value: string | number | null; status: string; available_at: string; source_id: string; phase: string };
export type PitCard = {
  ipo_id: string; name: string; as_of: string; list_date: string; visible: PitFact[]; hidden: PitFact[];
  signals: { strategy: string; action: string; reasons: string[] }[]; bars_visible: number; note: string;
};

export const strategyApi = {
  catalog: () => request<{ strategies: StrategyInfo[]; min_n: number }>("/api/strategies"),
  ipos: () => request<{ ipos: { ipo_id: string; name: string; list_date: string; split: string }[] }>("/api/ipos"),
  run: (strategy: string, overrides: Record<string, number>) => request<BacktestResult>("/api/strategy/run", { strategy, overrides }),
  card: (ipo_id: string, as_of: string) => request<PitCard>("/api/strategy/card", { ipo_id, as_of }),
  basicStats: () => request<{ doc: string; file: string | null }>("/api/basic_stats"),
};
