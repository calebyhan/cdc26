import type { TooltipContentProps } from "recharts";
import { money } from "@/lib/types";

type Props = Pick<TooltipContentProps, "active" | "payload" | "label"> & {
  mode: "currency" | "count";
  note: string;
  /** Read the displayed value from this payload field instead of the bar height. */
  valueKey?: string;
};

/** Shared chart hover/focus presentation; raw data keys never become UI labels. */
export function ChartTooltip({
  active,
  payload,
  label,
  mode,
  note,
  valueKey,
}: Props) {
  if (!active || !payload?.length) return null;
  const entry = payload[0];
  const title =
    typeof entry.payload?.label === "string"
      ? entry.payload.label
      : String(label ?? "Record");
  const raw = valueKey ? entry.payload?.[valueKey] : entry.value;
  const value = typeof raw === "number" && Number.isFinite(raw) ? raw : null;
  const formatted =
    value === null
      ? "Unknown"
      : mode === "currency"
        ? money(value)
        : new Intl.NumberFormat("en-US").format(value);

  return (
    <div className="chart-tooltip" role="status">
      <div className="chart-tooltip-title">{title}</div>
      <div className="chart-tooltip-value-row">
        <span className="chart-tooltip-measure">
          <i
            style={{
              background:
                entry.payload?.color || entry.color || entry.fill || "#2e7d70",
            }}
          />
          {mode === "currency" ? "Amount" : "Keyword matches"}
        </span>
        <strong>{formatted}</strong>
      </div>
      <div className="chart-tooltip-note">{note}</div>
    </div>
  );
}
