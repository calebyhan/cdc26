import "server-only";

import { readFile } from "node:fs/promises";
import path from "node:path";
import type {
  AtlasSummary,
  Filer,
  Hospital,
  PriceData,
  StateRow,
} from "@/lib/atlas";

/** UI actions the guide may ask the browser to perform. */
export type AssistantAction =
  | { type: "open_workspace"; workspace: Workspace }
  | { type: "open_state"; state: string; hospitalId?: string | null }
  | { type: "open_navigator"; state: string; hospitalId?: string | null };

export const WORKSPACES = ["atlas", "upload", "demo", "evidence", "research"] as const;
type Workspace = (typeof WORKSPACES)[number];

type PublicData = {
  summary: AtlasSummary;
  hospitals: Hospital[];
  filers: Filer[];
  prices: PriceData;
};

let cache: Promise<PublicData> | null = null;

/** Public atlas artifacts only; never case data. Safe to keep in memory. */
function publicData(): Promise<PublicData> {
  cache ??= (async () => {
    const dir = path.join(process.cwd(), "public", "atlas");
    const read = async <T>(name: string) =>
      JSON.parse(await readFile(path.join(dir, name), "utf8")) as T;
    const [summary, hospitals, schedule, prices] = await Promise.all([
      read<AtlasSummary>("states.json"),
      read<{ fields: string[]; rows: unknown[][] }>("hospitals.json"),
      read<{ filers: Filer[] }>("schedule_h.json"),
      read<PriceData>("prices.json"),
    ]);
    return {
      summary,
      hospitals: hospitals.rows.map(
        (row) =>
          Object.fromEntries(
            hospitals.fields.map((field, i) => [field, row[i]]),
          ) as Hospital,
      ),
      filers: schedule.filers,
      prices,
    };
  })().catch((error) => {
    cache = null;
    throw error;
  });
  return cache;
}

const round = (value: number | null | undefined, digits = 2) =>
  value == null ? null : Math.round(value * 10 ** digits) / 10 ** digits;

const stateCode = (value: unknown) =>
  typeof value === "string" && /^[A-Za-z]{2}$/.test(value.trim())
    ? value.trim().toUpperCase()
    : null;

function findState(data: PublicData, value: unknown): StateRow | null {
  const code = stateCode(value);
  if (code) return data.summary.states.find((s) => s.state_abbr === code) ?? null;
  if (typeof value !== "string") return null;
  const name = value.trim().toLowerCase();
  return data.summary.states.find((s) => s.name.toLowerCase() === name) ?? null;
}

function stateProfile(data: PublicData, row: StateRow) {
  const monthly = row.monthly;
  const recent = monthly.slice(-12).reduce((a, b) => a + b, 0);
  const prior = monthly.slice(-24, -12).reduce((a, b) => a + b, 0);
  return {
    state: row.state_abbr,
    name: row.name,
    year: data.summary.rate_year,
    complaints: row.complaints,
    complaints_per_100k: round(row.rate_per_100k),
    rate_95ci: row.rate_ci,
    us_rate_per_100k: data.summary.national.rate_per_100k,
    ratio_to_us_rate: row.ratio_to_national,
    ratio_to_expected_after_uninsured_and_poverty: row.adjusted_ratio ?? null,
    debt_was_paid_complaints: row.paid,
    last_12_months: recent,
    prior_12_months: prior,
    top_issues: row.issues.slice(0, 4),
    company_responses: row.responses,
    companies_named_most: row.top_companies.slice(0, 5),
    uninsured_rate: round(row.uninsured_rate, 4),
    poverty_rate: round(row.poverty_rate, 4),
    median_household_income: row.median_income,
    hospitals_by_ownership: row.hospitals,
    nonprofit_hospitals: row.nonprofit_hospitals,
    nonprofit_with_linked_schedule_h_policy: row.nonprofit_linked,
    schedule_h_summary: row.schedule_h,
    notes:
      "CFPB complaints are consumer reports, not verified findings; most name a collector, not a hospital.",
  };
}

function hospitalDetails(data: PublicData, hospital: Hospital) {
  const ref = hospital.policy_ref;
  const filer = ref ? data.filers[ref[0]] : null;
  const policy = ref && filer ? filer.policies[ref[1]] : null;
  const prices = data.prices.hospitals[hospital.id];
  return {
    hospital_id: hospital.id,
    name: hospital.name,
    city: hospital.city,
    state: hospital.state,
    ownership: hospital.ownership,
    type: hospital.type,
    emergency_services: hospital.emergency,
    schedule_h: policy
      ? {
          filer: filer!.name,
          tax_year: filer!.tax_year,
          free_care_up_to_pct_poverty_level: policy.free_fpg,
          discounted_care_up_to_pct_poverty_level: policy.discount_fpg,
          policy_url: policy.fap_url,
          application_url: policy.application_url,
          notice_on_bills: policy.notice_on_bills,
          translated: policy.translated,
          collection_actions_permitted_before_eligibility_efforts:
            policy.ecas_permitted_before_efforts,
          reported_taking_actions_before_eligibility_efforts:
            policy.ecas_before_reasonable_efforts,
          caveat:
            "Self-reported IRS filing, linked to this CMS hospital by ZIP code and name; not audited.",
        }
      : hospital.ownership_class === "nonprofit"
        ? "No Schedule H filing was linked to this nonprofit hospital."
        : "Schedule H applies only to nonprofit hospitals.",
    posted_prices_usd: prices
      ? Object.fromEntries(
          Object.entries(prices.prices).map(([code, p]) => [
            `${code} ${data.prices.basket[code]}`,
            {
              cash_price: p.cash_cents == null ? null : p.cash_cents / 100,
              insurer_negotiated_median:
                p.negotiated_median_cents == null ? null : p.negotiated_median_cents / 100,
              gross_charge: p.gross_cents == null ? null : p.gross_cents / 100,
            },
          ]),
        )
      : null,
  };
}

export const functionDeclarations = [
  {
    name: "get_state_profile",
    description:
      "Public-data profile for one U.S. state: 2025 CFPB medical-debt collection complaints (count, rate per 100k, ratio to U.S. and to expected), trend, issues, company responses, ACS uninsured/poverty, hospitals, and Schedule H policy summary.",
    parameters: {
      type: "object",
      properties: { state: { type: "string", description: "Two-letter code or full state name" } },
      required: ["state"],
    },
  },
  {
    name: "rank_states",
    description:
      "List states by a complaint measure. Use for questions like 'where is it highest'. Never rank hospitals.",
    parameters: {
      type: "object",
      properties: {
        metric: {
          type: "string",
          enum: ["complaints_per_100k", "ratio_to_expected", "complaints_per_10k_uninsured", "debt_was_paid_share"],
        },
        order: { type: "string", enum: ["highest", "lowest"] },
        limit: { type: "integer" },
      },
      required: ["metric"],
    },
  },
  {
    name: "find_hospitals",
    description:
      "Search CMS hospitals in a state by name; returns IDs, ownership, and whether a Schedule H financial-assistance policy is linked.",
    parameters: {
      type: "object",
      properties: {
        state: { type: "string" },
        query: { type: "string", description: "Part of the hospital name or city" },
      },
      required: ["state"],
    },
  },
  {
    name: "get_hospital_details",
    description:
      "Filed financial-assistance policy (IRS Schedule H) and any posted prices for one hospital by its CMS ID.",
    parameters: {
      type: "object",
      properties: { hospital_id: { type: "string" } },
      required: ["hospital_id"],
    },
  },
  {
    name: "open_state",
    description: "Show a state (and optionally a hospital) on the community map for the user.",
    parameters: {
      type: "object",
      properties: { state: { type: "string" }, hospital_id: { type: "string" } },
      required: ["state"],
    },
  },
  {
    name: "open_workspace",
    description:
      "Switch the app view: atlas = community map, upload = upload documents, demo = case overview/timeline, evidence = documents & review, research = complaint research.",
    parameters: {
      type: "object",
      properties: { workspace: { type: "string", enum: [...WORKSPACES] } },
      required: ["workspace"],
    },
  },
  {
    name: "open_navigator",
    description:
      "Open the evidence navigator (upload view) with a state and optional hospital preselected so the user can work on their own bills.",
    parameters: {
      type: "object",
      properties: { state: { type: "string" }, hospital_id: { type: "string" } },
      required: ["state"],
    },
  },
];

export async function runTool(
  name: string,
  args: Record<string, unknown>,
  actions: AssistantAction[],
): Promise<Record<string, unknown>> {
  const data = await publicData();
  switch (name) {
    case "get_state_profile": {
      const row = findState(data, args.state);
      return row ? stateProfile(data, row) : { error: "Unknown state." };
    }
    case "rank_states": {
      const metric = String(args.metric);
      const value = (s: StateRow) =>
        metric === "ratio_to_expected"
          ? s.adjusted_ratio ?? null
          : metric === "complaints_per_10k_uninsured"
            ? s.per_10k_uninsured
            : metric === "debt_was_paid_share"
              ? s.complaints >= 50
                ? s.paid / s.complaints
                : null
              : s.rate_per_100k;
      const limit = Math.min(Math.max(Number(args.limit) || 5, 1), 15);
      const rows = data.summary.states
        .filter((s) => value(s) != null && s.complaints >= 20)
        .sort((a, b) =>
          args.order === "lowest"
            ? (value(a) as number) - (value(b) as number)
            : (value(b) as number) - (value(a) as number),
        )
        .slice(0, limit)
        .map((s) => ({ state: s.state_abbr, name: s.name, value: round(value(s), 3), complaints: s.complaints }));
      return {
        metric,
        year: data.summary.rate_year,
        states: rows,
        note: "States with fewer than 20 complaints are excluded as unstable.",
      };
    }
    case "find_hospitals": {
      const row = findState(data, args.state);
      if (!row) return { error: "Unknown state." };
      const query = typeof args.query === "string" ? args.query.toLowerCase().trim() : "";
      const matches = data.hospitals
        .filter(
          (h) =>
            h.state === row.state_abbr &&
            (!query ||
              h.name.toLowerCase().includes(query) ||
              h.city.toLowerCase().includes(query)),
        )
        .slice(0, 12)
        .map((h) => ({
          hospital_id: h.id,
          name: h.name,
          city: h.city,
          ownership: h.ownership_class,
          schedule_h_policy_linked: Boolean(h.policy_ref),
          has_posted_prices: Boolean(h.has_prices),
        }));
      return { state: row.state_abbr, hospitals: matches };
    }
    case "get_hospital_details": {
      const hospital = data.hospitals.find((h) => h.id === String(args.hospital_id));
      return hospital ? hospitalDetails(data, hospital) : { error: "Unknown hospital ID." };
    }
    case "open_state":
    case "open_navigator": {
      const row = findState(data, args.state);
      if (!row) return { error: "Unknown state." };
      const hospital =
        typeof args.hospital_id === "string"
          ? data.hospitals.find(
              (h) => h.id === args.hospital_id && h.state === row.state_abbr,
            )
          : undefined;
      actions.push({
        type: name,
        state: row.state_abbr,
        hospitalId: hospital?.id ?? null,
      });
      return { ok: true, opened: row.name, hospital: hospital?.name ?? null };
    }
    case "open_workspace": {
      const workspace = WORKSPACES.find((w) => w === args.workspace);
      if (!workspace) return { error: "Unknown workspace." };
      actions.push({ type: "open_workspace", workspace });
      return { ok: true, workspace };
    }
    default:
      return { error: "Unknown tool." };
  }
}
