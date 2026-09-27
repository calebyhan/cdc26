/** Public-data community atlas: types, loaders, and formatting helpers. */

export type Labeled = { label: string; count: number };

export type PolicySummary = {
  facilities_with_policy: number;
  median_free_fpg: number | null;
  median_discount_fpg: number | null;
  share_free_fpg_at_least_200: number | null;
  share_ecas_permitted_before_efforts: number | null;
  share_credit_reporting_before_efforts: number | null;
  share_legal_process_before_efforts: number | null;
  share_ecas_taken_before_efforts: number | null;
  share_notice_on_bills: number | null;
};

export type StateRow = {
  fips: string;
  name: string;
  state_abbr: string;
  population: number;
  uninsured: number;
  uninsured_rate: number;
  poverty_rate: number;
  median_income: number | null;
  disability_rate: number | null;
  rent_burden_rate: number | null;
  complaints: number;
  rate_per_100k: number;
  rate_ci: [number, number];
  per_10k_uninsured: number | null;
  ratio_to_national: number;
  expected_adjusted?: number;
  adjusted_ratio?: number | null;
  paid: number;
  not_owed: Labeled[];
  issues: Labeled[];
  responses: Labeled[];
  top_companies: Labeled[];
  timely: number;
  servicemember: number;
  older_american: number;
  zip5: number;
  monthly: number[];
  hospitals: Partial<Record<Ownership, number>>;
  nonprofit_hospitals: number;
  nonprofit_linked: number;
  schedule_h: PolicySummary;
  bivariate: [number, number] | null;
};

export type AtlasSummary = {
  generated_at: string;
  rate_year: number;
  months: string[];
  national: {
    count: number;
    rate_per_100k: number;
    population: number;
    paid: number;
    issues: Labeled[];
    not_owed: Labeled[];
    responses: Labeled[];
    monthly: number[];
    timely: number;
  };
  model: {
    features: string[];
    rate_ratio_per_sd: Record<string, number>;
    feature_sd: Record<string, number>;
    pearson_dispersion: number;
    n: number;
  };
  bivariate_cuts: { uninsured_rate: number[]; rate_per_100k: number[] };
  counts: Record<string, number>;
  states: StateRow[];
};

export type CountyRow = {
  fips: string;
  name: string;
  state: string;
  population: number;
  uninsured_rate: number | null;
  poverty_rate: number | null;
  median_income: number | null;
  complaints: number;
  annual_rate_per_100k: number | null;
};

export type CountyData = {
  years: [number, number];
  min_count: number;
  unmapped_by_state: Record<string, number>;
  counties: CountyRow[];
};

export type Ownership = "nonprofit" | "for_profit" | "government" | "other";

export type Hospital = {
  id: string;
  name: string;
  city: string;
  state: string;
  zip: string;
  county_fips: string | null;
  type: string;
  ownership: string;
  ownership_class: Ownership;
  emergency: boolean;
  rating: number | null;
  lat: number | null;
  lon: number | null;
  policy_ref: [number, number] | null;
  has_prices: boolean;
};

export type PricePoint = {
  gross_cents: number | null;
  cash_cents: number | null;
  negotiated_min_cents: number | null;
  negotiated_median_cents: number | null;
  negotiated_max_cents: number | null;
  payer_rates: number;
};

export type PriceData = {
  basket: Record<string, string>;
  status: Record<string, number>;
  hospitals: Record<
    string,
    { location_name: string; mrf_url: string; prices: Record<string, PricePoint> }
  >;
};

export type Policy = {
  free_fpg: number | null;
  discount_fpg: number | null;
  criteria: string[];
  fap_url: string | null;
  application_url: string | null;
  summary_url: string | null;
  notice_on_bills: boolean | null;
  translated: boolean | null;
  nonpayment_actions_policy: boolean | null;
  no_ecas_before_efforts: boolean | null;
  ecas_permitted_before_efforts: string[];
  ecas_before_reasonable_efforts: boolean | null;
  emergency_care_policy: boolean | null;
  charged_more_than_agb: boolean | null;
  charged_gross_charges: boolean | null;
};

export type Filer = {
  ein: string;
  name: string;
  state: string;
  tax_year: string | null;
  tax_period_end: string | null;
  object_id: string;
  free_fpg: number | null;
  discount_fpg: number | null;
  financial_assistance_cost: number | null;
  financial_assistance_pct_expense: number | null;
  community_benefit_net: number | null;
  bad_debt_expense: number | null;
  facility_count: number;
  policies: Policy[];
};

export type Source = {
  id: string;
  name: string;
  url: string;
  use: string;
  limits: string;
  instructions?: string;
};

export type Manifest = {
  generated_at: string;
  sources: Source[];
  counts: Record<string, number>;
};

export type LinkedPolicy = { filer: Filer; policy: Policy };

export type Atlas = {
  summary: AtlasSummary;
  counties: CountyData;
  hospitals: Hospital[];
  filers: Filer[];
  manifest: Manifest;
  prices: PriceData;
};

const cache: { atlas?: Promise<Atlas> } = {};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Couldn’t load ${path}`);
  return response.json() as Promise<T>;
}

/** Load every public atlas artifact once per page session. */
export function loadAtlas(): Promise<Atlas> {
  cache.atlas ??= Promise.all([
    getJson<AtlasSummary>("/atlas/states.json"),
    getJson<CountyData>("/atlas/counties.json"),
    getJson<{ fields: string[]; rows: unknown[][] }>("/atlas/hospitals.json"),
    getJson<{ filers: Filer[] }>("/atlas/schedule_h.json"),
    getJson<Manifest>("/atlas/manifest.json"),
    getJson<PriceData>("/atlas/prices.json"),
  ])
    .then(([summary, counties, hospitals, schedule, manifest, prices]) => ({
      summary,
      counties,
      hospitals: hospitals.rows.map(
        (row) =>
          Object.fromEntries(
            hospitals.fields.map((field, index) => [field, row[index]]),
          ) as Hospital,
      ),
      filers: schedule.filers,
      manifest,
      prices,
    }))
    .catch((error) => {
      cache.atlas = undefined;
      throw error;
    });
  return cache.atlas;
}

export function policyFor(
  atlas: Pick<Atlas, "filers">,
  hospital: Hospital | undefined | null,
): LinkedPolicy | null {
  if (!hospital?.policy_ref) return null;
  const filer = atlas.filers[hospital.policy_ref[0]];
  const policy = filer?.policies[hospital.policy_ref[1]];
  return filer && policy ? { filer, policy } : null;
}

export const ownershipLabel: Record<Ownership, string> = {
  nonprofit: "Nonprofit",
  for_profit: "For-profit",
  government: "Government",
  other: "Other",
};

/** Categorical slots 1–3 (validated all-pairs for dot layers). */
export const ownershipColor: Record<Ownership, string> = {
  nonprofit: "#2a78d6",
  for_profit: "#eb6834",
  government: "#1baf7a",
  other: "#8a8f8c",
};

export const ecaLabel: Record<string, string> = {
  credit_reporting: "Reporting to credit agencies",
  selling_debt: "Selling the debt",
  legal_process: "Actions requiring a legal or judicial process",
  defer_or_deny_care: "Deferring or denying care for a prior unpaid bill",
  other: "Other similar actions",
};

export const dollars = (cents: number | null | undefined) =>
  cents == null
    ? "—"
    : (cents / 100).toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: cents >= 100_000 ? 0 : 2,
      });

export const pct = (value: number | null | undefined, digits = 0) =>
  value == null ? "—" : `${(value * 100).toFixed(digits)}%`;

export const num = (value: number | null | undefined, digits = 0) =>
  value == null
    ? "—"
    : value.toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });

export const fpg = (value: number | null | undefined) =>
  value == null ? "Not reported" : `${Math.round(value)}% of poverty level`;

export const monthLabel = (month: string) => {
  const [year, m] = month.split("-").map(Number);
  return new Date(Date.UTC(year, m - 1, 1)).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
};

export const safeUrl = (value: string | null | undefined) => {
  if (!value) return null;
  const trimmed = value.trim();
  const url = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.toString()
      : null;
  } catch {
    return null;
  }
};

/** Last 12 complete months vs the 12 before, from a monthly series. */
export function yearOverYear(monthly: number[]) {
  const recent = monthly.slice(-12).reduce((a, b) => a + b, 0);
  const prior = monthly.slice(-24, -12).reduce((a, b) => a + b, 0);
  return { recent, prior, change: prior ? recent / prior - 1 : null };
}
