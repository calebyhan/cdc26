export type Fact = {
  value: string;
  quote: string;
  page: number;
  confirmed: boolean;
  origin: "document" | "user";
};
export type Document = {
  id: string;
  kind: string;
  title: string;
  text: string;
  fields: Record<string, Fact>;
  included: boolean;
  extraction_method: string;
  warnings: string[];
};
export type Finding = {
  code: string;
  title: string;
  detail: string;
  severity: string;
  refs: string[];
};
export type LedgerRow = { label: string; cents: number; refs: string[] };
export type Result = {
  findings: Finding[];
  ledger: LedgerRow[];
  collection_cents: number | null;
  supported_balance_cents: number | null;
  applied_payments_cents: number;
  matched_document_ids: string[];
  excluded_document_ids: string[];
};
export type Analysis = {
  result: Result;
  drafts: Record<"provider" | "collector", string>;
};
export type Count = { label: string; count: number };
export type Rule = Count & { id: string; description: string };
export type ResponseGroup = {
  label: string;
  total: number;
  responses: Count[];
};
export type Bootstrap = {
  scenarios: Record<string, string>;
  examples: Record<string, Document[]>;
  document_sources: Record<string, Record<string, string>>;
  field_labels: Record<string, string>;
  kinds: Record<string, string>;
  ai_available: boolean;
  research: {
    retrieved_at: string;
    api: {
      total_complaints: number;
      not_owed_subissues: Count[];
      issue_counts: Count[];
      source_url: string;
      response_outcomes?: {
        groups: ResponseGroup[];
        source_urls: string[];
        caveat: string;
      };
    };
    archive: {
      unique_narratives: number;
      period: string;
      source_url: string;
      patterns: Rule[];
      document_mentions: Rule[];
      pattern_document_matrix: {
        pattern_id: string;
        document_id: string;
        count: number;
      }[];
    };
    caveats: string[];
  };
};
export const money = (cents: number | null | undefined) =>
  cents == null
    ? "Unknown"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      }).format(cents / 100);
export const shortDate = (value?: string) =>
  value
    ? new Date(`${value}T12:00:00`).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      })
    : "Date unknown";
export async function api<T>(
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api/case", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
    signal,
  });
  const result = await response.json();
  if (!response.ok || result.error)
    throw new Error(
      result.error || "Could not connect to the evidence engine.",
    );
  return result as T;
}
