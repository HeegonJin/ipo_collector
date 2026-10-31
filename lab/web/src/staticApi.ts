// 서버 없이 브라우저에서 api.ts 와 같은 일을 한다: lab_data.json 을 읽어 engine.ts 로 계산하고, 시도 횟수·검증 구간 기록은 이 브라우저(localStorage)에 남긴다.
// 검증 구간 잠금은 이 브라우저 안에서만 지켜지는 약한 잠금이다 (자료 파일이 공개돼 있으므로 우회하려면 할 수 있다 — 스터디 신뢰가 전제).
import type { EvalResult, Meta, Params, ValidResult } from "./api";
import { chanceBest, Engine, mask, paramsHash, Row, Costs, Cfg, Eff } from "./engine";

type Data = { meta: Meta; rows: Row[]; costs: Costs; cfg: Cfg };
let loaded: Promise<{ data: Data; engine: Engine }> | null = null;

function load() {
  loaded ??= fetch("lab_data.json").then((r) => {
    if (!r.ok) throw new Error(`데이터 파일을 읽지 못했습니다 (${r.status})`);
    return r.json();
  }).then((data: Data) => ({ data, engine: new Engine(data.meta.conditions, data.rows, data.costs, data.cfg) }));
  return loaded;
}

const mem: Record<string, string> = {};
const store = {
  get<T>(key: string, fallback: T): T {
    try { return JSON.parse(localStorage.getItem(key) ?? mem[key] ?? "null") ?? fallback; } catch { return fallback; }
  },
  set(key: string, value: unknown) {
    const text = JSON.stringify(value);
    mem[key] = text;
    try { localStorage.setItem(key, text); } catch { /* 저장 불가(사생활 보호 모드): 이 탭이 열려 있는 동안만 유지 */ }
  },
};
type Trial = { ts: string; hash: string; params: Eff };
const trials = () => store.get<Trial[]>("lab_trials_v1", []);
const distinct = (t: Trial[]) => new Set(t.map((x) => x.hash)).size;

function trialInfo(cfg: Cfg, se: number | null | undefined) {
  const t = trials(), d = distinct(t);
  return { distinct: d, total: t.length, warn: d >= cfg.trials_warn_at, warn_at: cfg.trials_warn_at, chance_best: chanceBest(d, se) };
}

export const staticApi = {
  meta: async (): Promise<Meta> => (await load()).data.meta,

  count: async (params: Params) => {
    const { engine } = await load();
    const r = engine.evaluate(engine.normalize(params), "train");
    return { n: r.stats.n ?? 0, pool: r.pool };
  },

  evaluate: async (params: Params): Promise<EvalResult> => {
    const { engine, data } = await load();
    const eff = engine.normalize(params);                       // 잘못된 파라미터는 여기서 예외, 시도로 세지 않는다
    const res = engine.evaluate(eff, "train");
    const hash = paramsHash(eff);
    store.set("lab_trials_v1", [...trials(), { ts: new Date().toISOString(), hash, params: eff }]);
    const stats = mask(res.stats, data.cfg.min_n);
    return {
      split: "train", params: eff, hash, stats, baseline: mask(res.baseline, data.cfg.min_n), excluded: res.excluded,
      lookahead: res.lookahead, pool: res.pool, design_external: engine.designExternal(eff),
      trades: stats.insufficient ? [] : res.trades.map((t) => ({ name: t.name, list_date: t.list_date, net_ret: t.net_ret })),
      robustness: engine.robustness(params, "train"), trials: trialInfo(data.cfg, res.stats.se),
    } as unknown as EvalResult;
  },

  validate: async (params: Params, confirm: string): Promise<ValidResult> => {
    const { engine, data } = await load();
    if (confirm !== data.cfg.confirm_phrase) throw new Error("확인 문구가 다릅니다 — 검증 구간은 한 번만 열어야 하므로 문구를 그대로 입력해야 합니다");
    const eff = engine.normalize(params);
    const hash = paramsHash(eff);
    if (!trials().some((t) => t.hash === hash)) throw new Error("학습 구간에서 먼저 평가한 조건만 검증 구간에서 열 수 있습니다");
    const prior = store.get<{ opened_at: string; tag: string }[]>("lab_valid_runs_v1", []);
    store.set("lab_valid_runs_v1", [...prior, { opened_at: new Date().toISOString(), tag: `lab ${hash}` }]);
    const res = engine.evaluate(eff, "valid");
    const warning = prior.length ? `검증 구간을 ${prior.length + 1}번째 열었다 (이전: ${prior[prior.length - 1].opened_at} · ${prior[prior.length - 1].tag}). 검증 구간을 반복해서 보면 사실상 학습에 쓰는 것이다 (D9)` : "";
    return { split: "valid", hash, stats: mask(res.stats, data.cfg.min_n), baseline: mask(res.baseline, data.cfg.min_n),
      excluded: res.excluded, lookahead: res.lookahead, warning } as unknown as ValidResult;
  },

  exportYaml: async (params: Params) => {
    const { engine } = await load();
    const eff = engine.normalize(params);
    const conds = Object.entries(eff.conditions).map(([k, [lo, hi]]) => `  ${k}:\n  - ${lo}\n  - ${hi}`).join("\n");
    const ext = engine.designExternal(eff);
    const lines = [`entry: ${eff.entry}`, `hold: ${eff.hold}`, conds ? `conditions:\n${conds}` : "conditions: {}",
      ext.length ? `design_external:\n${ext.map((x) => `- ${x}`).join("\n")}` : "design_external: []",
      `lookahead_upper_bound: ${eff.entry === "d0_close" && Object.keys(eff.conditions).some((c) => engine.byId[c].phase === "d0")}`,
      `trials_distinct: ${distinct(trials())}`, "evaluated_on:\n- train",
      "note: 탐색 결과 초안이다 (검증 구간 결과는 포함하지 않음). 채택하려면 사람이 새 버전 config 로 고정하고 forward 구간에서 확인한다."];
    return { yaml: lines.join("\n") + "\n" };
  },
};
