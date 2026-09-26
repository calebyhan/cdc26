import { ArrowRight } from "lucide-react";
import type { Bootstrap } from "@/lib/types";

type Research = Bootstrap["research"];

const responseColors: Record<string, string> = {
  "Closed with explanation": "#b7c4bd",
  "Closed with non-monetary relief": "#2e7d70",
  "Closed with monetary relief": "#263c35",
  "Untimely response": "#ce8d6e",
};
const pct = (count: number, total: number) =>
  `${((100 * count) / total).toFixed(count / total < 0.01 ? 1 : 0)}%`;

/** Company-reported outcomes; stacked to 100% so both groups compare directly. */
export function ResponseOutcomes({ research }: { research: Research }) {
  const outcome = research.api.response_outcomes;
  if (!outcome) return null;
  const paid = outcome.groups[1];
  const count = (label: string) =>
    paid.responses.find((item) => item.label === label)?.count ?? 0;
  const explained = count("Closed with explanation");
  const monetary = count("Closed with monetary relief");
  return (
    <div className="panel response-panel">
      <h2>How companies responded</h2>
      <p className="response-headline">
        <strong>{pct(explained, paid.total)}</strong> of “Debt was paid”
        complaints were closed with an explanation.{" "}
        <strong>{monetary.toLocaleString()}</strong> of{" "}
        {paid.total.toLocaleString()} ended with monetary relief.
      </p>
      <div className="response-rows">
        {outcome.groups.map((group) => (
          <div className="response-row" key={group.label}>
            <div className="response-label">
              {group.label}
              <small>{group.total.toLocaleString()} complaints · 2025</small>
            </div>
            <div
              className="response-bar"
              role="img"
              aria-label={`${group.label}: ${group.responses
                .map((r) => `${r.label} ${r.count}`)
                .join(", ")}`}
            >
              {group.responses.map((item) => (
                <span
                  key={item.label}
                  title={`${item.label}: ${item.count.toLocaleString()} (${pct(item.count, group.total)})`}
                  style={{
                    width: `${(100 * item.count) / group.total}%`,
                    background: responseColors[item.label] || "#d5dbd7",
                  }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="response-legend">
        {paid.responses.map((item) => (
          <span key={item.label}>
            <i style={{ background: responseColors[item.label] }} />
            {item.label} · {item.count.toLocaleString()}
          </span>
        ))}
      </div>
      <p className="footnote">{outcome.caveat}</p>
    </div>
  );
}

const checks = [
  {
    kind: "document",
    id: "bill",
    noun: "mention a bill or statement",
    check: "The provider statement is rebuilt line by line.",
  },
  {
    kind: "pattern",
    id: "verification_language",
    noun: "ask for verification or proof",
    check: "Every amount opens its source passage.",
  },
  {
    kind: "pattern",
    id: "identity_language",
    noun: "question whose debt it is",
    check: "Provider, patient, account, and visit date must match exactly.",
  },
  {
    kind: "document",
    id: "receipt",
    noun: "mention a receipt or payment proof",
    check: "Only a completed receipt counts as payment; an EOB never does.",
  },
];

/** Keyword co-occurrence between complaint language and documents mentioned. */
export function PatternMatrix({ research }: { research: Research }) {
  const { archive } = research;
  const cell = (pattern: string, document: string) =>
    archive.pattern_document_matrix.find(
      (item) => item.pattern_id === pattern && item.document_id === document,
    )?.count ?? 0;
  const max = Math.max(
    1,
    ...archive.pattern_document_matrix.map((c) => c.count),
  );
  const countFor = (kind: string, id: string) =>
    (kind === "pattern" ? archive.patterns : archive.document_mentions).find(
      (item) => item.id === id,
    )?.count ?? 0;
  return (
    <div className="analysis-grid matrix-grid">
      <div className="panel">
        <h2>Complaint language × documents mentioned</h2>
        <p className="muted small">
          Narratives matching both rules, among{" "}
          {archive.unique_narratives.toLocaleString()} unique narratives ·{" "}
          {archive.period}
        </p>
        <table className="heatmap">
          <thead>
            <tr>
              <th />
              {archive.document_mentions.map((doc) => (
                <th key={doc.id} scope="col">
                  {doc.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {archive.patterns.map((pattern) => (
              <tr key={pattern.id}>
                <th scope="row">{pattern.label}</th>
                {archive.document_mentions.map((doc) => {
                  const value = cell(pattern.id, doc.id);
                  const strength = value / max;
                  return (
                    <td
                      key={doc.id}
                      style={{
                        background: `rgba(46, 125, 112, ${0.06 + 0.84 * strength})`,
                        color: strength > 0.45 ? "white" : "#263c35",
                      }}
                    >
                      {value}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h2>What the complaints shaped</h2>
        <p className="muted small">
          Recurring themes became evidence checks in the case workflow
        </p>
        <ul className="shaped-checks">
          {checks.map((item) => (
            <li key={item.id}>
              <strong>{countFor(item.kind, item.id).toLocaleString()}</strong>
              <span>
                narratives {item.noun}
                <em>
                  <ArrowRight size={12} />
                  {item.check}
                </em>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
