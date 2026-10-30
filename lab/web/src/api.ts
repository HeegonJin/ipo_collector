export type Condition = {
  id: string; label: string; hint: string; phase: "pre" | "d0"; unit: string;
  min: number; max: number; step: number; in_design: boolean;
};
export type Meta = {
  conditions: Condition[];
  entries: Record<string, { label: string; in_design: boolean }>;
  holds: number[]; min_n: number; trials_warn_at: number; confirm_phrase: string;
  split_sizes: Record<string, number>; data_end?: string;
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

async function request<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error ?? `요청 실패 (${res.status})`);
  return data as T;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  count: (params: Params) => request<{ n: number; pool: number }>("/api/count", { params }),
  evaluate: (params: Params) => request<EvalResult>("/api/evaluate", { params }),
  validate: (params: Params, confirm: string) => request<ValidResult>("/api/validate", { params, confirm }),
  exportYaml: (params: Params) => request<{ yaml: string }>("/api/export", { params }),
};
