import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { money, type Result } from "@/lib/types";
import { ChartTooltip } from "@/app/components/chart-tooltip";

const SUPPORTED_ROW = "Balance supported by supplied records";
const STATEMENT_ROW = "Provider statement balance";
const short: Record<string, string> = {
  "Provider charges": "Charges",
  "Contractual adjustment": "Adjustment",
  "Posted insurer payment": "Insurance paid",
  "Patient payments already posted": "Earlier payments",
  [STATEMENT_ROW]: "Bill balance",
  "Matching completed payment after statement": "Receipt",
};
const colors = {
  increase: "#9fb3aa",
  decrease: "#2e7d70",
  total: "#263c35",
  notice: "#ce8d6e",
};

type Step = {
  label: string;
  base: number;
  size: number;
  cents: number | null;
  color: string;
  refs: string[];
};

/** Walks the provider arithmetic down to the supported balance, beside the notice. */
function steps(
  result: Result,
  noticeRefs: string[],
): (Step & { tag: string })[] {
  const out: Step[] = [];
  let running = 0;
  for (const row of result.ledger) {
    if (row.label === SUPPORTED_ROW) continue;
    if (row.label === STATEMENT_ROW) {
      running = row.cents;
      out.push({
        label: short[row.label],
        base: 0,
        size: row.cents,
        cents: row.cents,
        color: colors.total,
        refs: row.refs,
      });
      continue;
    }
    if (row.cents === 0 && row.label !== "Provider charges") continue;
    const next = running + row.cents;
    out.push({
      label: short[row.label] || row.label,
      base: Math.min(running, next),
      size: Math.abs(row.cents),
      cents: row.cents,
      color: row.cents > 0 ? colors.increase : colors.decrease,
      refs: row.refs,
    });
    running = next;
  }
  const supported = result.ledger.find((row) => row.label === SUPPORTED_ROW);
  out.push({
    label: "Supported",
    base: 0,
    size: result.supported_balance_cents ?? 0,
    cents: result.supported_balance_cents,
    color: colors.total,
    refs: supported?.refs || [],
  });
  out.push({
    label: "Notice",
    base: 0,
    size: result.collection_cents ?? 0,
    cents: result.collection_cents,
    color: colors.notice,
    refs: noticeRefs,
  });
  return out.map((step) => ({
    ...step,
    tag: step.cents === null ? "Withheld" : money(step.cents),
  }));
}

export function MoneyWaterfall({
  result,
  noticeRefs,
  onSelect,
}: {
  result: Result;
  noticeRefs: string[];
  onSelect: (refs: string[]) => void;
}) {
  const data = steps(result, noticeRefs);
  return (
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <BarChart
        accessibilityLayer
        data={data}
        margin={{ left: 0, right: 8, top: 26, bottom: 4 }}
      >
        <CartesianGrid vertical={false} stroke="#e9eeed" />
        <XAxis
          dataKey="label"
          interval={0}
          tick={{ fontSize: 10, fill: "#45534f" }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tickFormatter={(value) => money(value).replace(".00", "")}
          tick={{ fontSize: 10, fill: "#7b8584" }}
          axisLine={false}
          tickLine={false}
          width={58}
        />
        <Tooltip
          content={(props) => (
            <ChartTooltip
              {...props}
              mode="currency"
              valueKey="cents"
              note="Click the bar to open its source"
            />
          )}
          cursor={{ fill: "#f3f6f1" }}
          isAnimationActive={false}
          wrapperStyle={{ outline: "none", zIndex: 10 }}
        />
        <Bar
          dataKey="base"
          stackId="walk"
          fill="transparent"
          tooltipType="none"
          isAnimationActive={false}
        />
        <Bar
          dataKey="size"
          stackId="walk"
          radius={[3, 3, 0, 0]}
          isAnimationActive={false}
          // Totals of $0 (or withheld) still need a visible mark for their label.
          minPointSize={(value, index) =>
            data[index]?.base === 0 && !value ? 3 : 0
          }
          cursor="pointer"
          onClick={(entry) => {
            const refs = (entry as unknown as { payload?: Step }).payload?.refs;
            if (refs?.length) onSelect(refs);
          }}
        >
          {data.map((step, index) => (
            <Cell
              key={`${step.label}-${index}`}
              fill={step.cents === null ? "transparent" : step.color}
              stroke={step.cents === null ? step.color : undefined}
              strokeDasharray={step.cents === null ? "3 3" : undefined}
            />
          ))}
          <LabelList
            dataKey="tag"
            position="top"
            style={{ fontSize: 10, fill: "#45534f" }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
