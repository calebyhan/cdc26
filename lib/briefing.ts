/** Printable advocate briefing for one state, built from public aggregates only. */

import {
  dollars,
  ecaLabel,
  fpg,
  monthLabel,
  num,
  pct,
  policyFor,
  safeUrl,
  yearOverYear,
  type Atlas,
  type StateRow,
} from "@/lib/atlas";

const escape = (value: unknown) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ] as string,
  );

export function briefingHtml(atlas: Atlas, row: StateRow): string {
  const { summary, counties } = atlas;
  const yoy = yearOverYear(row.monthly);
  const lastMonth = monthLabel(summary.months[summary.months.length - 1]);
  const topCounties = counties.counties
    .filter(
      (c) =>
        c.state === row.state_abbr &&
        c.annual_rate_per_100k != null &&
        c.complaints >= 20,
    )
    .sort((a, b) => (b.annual_rate_per_100k ?? 0) - (a.annual_rate_per_100k ?? 0))
    .slice(0, 10);
  const nonprofit = atlas.hospitals
    .filter((h) => h.state === row.state_abbr && h.ownership_class === "nonprofit")
    .map((h) => ({ h, linked: policyFor(atlas, h) }))
    .filter((item) => item.linked)
    .sort((a, b) => a.h.name.localeCompare(b.h.name));
  const h = row.schedule_h;
  const issueRows = row.issues
    .slice(0, 6)
    .map(
      (issue) =>
        `<tr><td>${escape(issue.label)}</td><td>${num(issue.count)}</td><td>${pct(
          issue.count / Math.max(row.complaints, 1),
        )}</td></tr>`,
    )
    .join("");
  const responseRows = row.responses
    .map(
      (r) =>
        `<tr><td>${escape(r.label)}</td><td>${num(r.count)}</td><td>${pct(
          r.count / Math.max(row.complaints, 1),
        )}</td></tr>`,
    )
    .join("");
  const countyRows = topCounties
    .map(
      (c) =>
        `<tr><td>${escape(c.name.split(",")[0])}</td><td>${num(c.complaints)}</td><td>${num(
          c.annual_rate_per_100k,
          1,
        )}</td><td>${pct(c.uninsured_rate, 1)}</td></tr>`,
    )
    .join("");
  const hospitalRows = nonprofit
    .map(({ h: hospital, linked }) => {
      const policy = linked!.policy;
      const url = safeUrl(policy.fap_url);
      const ecas = policy.ecas_permitted_before_efforts.length
        ? policy.ecas_permitted_before_efforts.map((e) => ecaLabel[e] ?? e).join("; ")
        : policy.no_ecas_before_efforts
          ? "None reported"
          : "Not reported";
      return `<tr><td>${escape(hospital.name)}<br><small>${escape(hospital.city)}</small></td><td>${
        policy.free_fpg != null ? `${num(policy.free_fpg)}%` : "—"
      }</td><td>${policy.discount_fpg != null ? `${num(policy.discount_fpg)}%` : "—"}</td><td>${escape(
        ecas,
      )}</td><td>${url ? `<a href="${escape(url)}">${escape(url)}</a>` : "—"}</td></tr>`;
    })
    .join("");
  const unlinked = row.nonprofit_hospitals - row.nonprofit_linked;
  const priced = atlas.hospitals.filter(
    (hospital) => hospital.state === row.state_abbr && atlas.prices.hospitals[hospital.id],
  );
  const priceRows = Object.entries(atlas.prices.basket)
    .map(([code, label]) => {
      const cash = priced
        .map((hospital) => atlas.prices.hospitals[hospital.id].prices[code]?.cash_cents)
        .filter((value): value is number => value != null);
      if (cash.length < 2) return "";
      const low = Math.min(...cash);
      const high = Math.max(...cash);
      return `<tr><td>${escape(label)} (${code})</td><td>${cash.length}</td><td>${dollars(low)} – ${dollars(
        high,
      )}</td><td>${(high / low).toFixed(1)}×</td></tr>`;
    })
    .join("");
  const generated = new Date().toISOString().slice(0, 10);

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escape(row.name)} medical-debt briefing</title>
<style>
body{font:13px/1.5 Arial,Helvetica,sans-serif;color:#263c35;max-width:860px;margin:32px auto;padding:0 20px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 8px;border-bottom:1px solid #e6eae6;padding-bottom:4px}
.eyebrow{font-size:10px;letter-spacing:.12em;color:#78817c}.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:18px 0}
.tiles div{border:1px solid #e6eae6;border-radius:8px;padding:12px}.tiles strong{display:block;font-size:22px;font-weight:400}
.tiles small,small{color:#78817c}table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:6px 4px;border-bottom:1px solid #e6eae6;vertical-align:top}
a{color:#2e6b58;word-break:break-all}.note{background:#faf1e9;border-radius:8px;padding:10px 12px;font-size:12px}
li{margin-bottom:4px}@media print{body{margin:0}a{color:inherit}}
</style></head><body>
<div class="eyebrow">NOT MY DEBT · COMMUNITY ADVOCATE BRIEFING · ${escape(generated)}</div>
<h1>${escape(row.name)}: reported medical-debt collection pressure</h1>
<p>Public-data profile for outreach planning by legal-aid, financial-counseling, and patient-advocacy teams.
It describes reported complaints and community context; it does not establish that any debt, collector, or hospital acted improperly.</p>
<div class="tiles">
<div><small>CFPB complaints, ${summary.rate_year}</small><strong>${num(row.complaints)}</strong><small>${num(
    row.rate_per_100k,
    1,
  )} per 100k residents (95% CI ${num(row.rate_ci[0], 1)}–${num(row.rate_ci[1], 1)})</small></div>
<div><small>Compared with the U.S. rate</small><strong>${num(row.ratio_to_national, 2)}×</strong><small>${
    row.adjusted_ratio != null
      ? `${num(row.adjusted_ratio, 2)}× the count expected from population, uninsured and poverty rates`
      : "Not included in the national model"
  }</small></div>
<div><small>“Debt was paid” complaints</small><strong>${num(row.paid)}</strong><small>${pct(
    row.paid / Math.max(row.complaints, 1),
  )} of this state’s ${summary.rate_year} complaints</small></div>
</div>
<p><strong>Trend.</strong> ${num(yoy.recent)} complaints in the 12 months through ${escape(lastMonth)}${
    yoy.change != null
      ? ` (${yoy.change >= 0 ? "+" : ""}${pct(yoy.change)} vs. the prior 12 months)`
      : ""
  }.</p>
<h2>Community context (ACS 2020–2024 5-year)</h2>
<p>${pct(row.uninsured_rate, 1)} uninsured (${num(row.uninsured)} people) · ${pct(
    row.poverty_rate,
    1,
  )} below the poverty line · median household income $${num(row.median_income)} · ${pct(
    row.disability_rate,
    1,
  )} with a disability · ${pct(row.rent_burden_rate)} of renters pay ≥30% of income on rent.</p>
<h2>What consumers reported (${summary.rate_year})</h2>
<table><thead><tr><th>Issue selected by consumer</th><th>Complaints</th><th>Share</th></tr></thead><tbody>${issueRows}</tbody></table>
<h2>How companies responded</h2>
<table><thead><tr><th>Company response</th><th>Complaints</th><th>Share</th></tr></thead><tbody>${responseRows}</tbody></table>
<p><small>Companies named most often: ${row.top_companies
    .map((c) => `${escape(c.label)} (${num(c.count)})`)
    .join("; ")}. These are usually collectors, not the original provider.</small></p>
${
  countyRows
    ? `<h2>Counties with the highest reported rates (${counties.years[0]}–${counties.years[1]})</h2>
<table><thead><tr><th>County</th><th>Complaints</th><th>Per 100k / year</th><th>Uninsured</th></tr></thead><tbody>${countyRows}</tbody></table>
<p><small>Counties with at least 20 complaints; ZIP codes assigned to counties by largest land-area overlap. ${num(
        counties.unmapped_by_state[row.state_abbr] ?? 0,
      )} complaints had a masked or unmatched ZIP.</small></p>`
    : ""
}
<h2>Hospital financial assistance (IRS Form 990 Schedule H)</h2>
<p>${num(row.hospitals.nonprofit ?? 0)} nonprofit, ${num(row.hospitals.for_profit ?? 0)} for-profit, and ${num(
    row.hospitals.government ?? 0,
  )} government hospitals (CMS). ${num(row.nonprofit_linked)} nonprofit hospitals are linked to a Schedule H policy${
    unlinked > 0 ? `; ${num(unlinked)} are not` : ""
  }. Median free-care limit: ${escape(fpg(h.median_free_fpg))}; median discount limit: ${escape(
    fpg(h.median_discount_fpg),
  )}. ${pct(h.share_ecas_permitted_before_efforts)} of linked facilities reported permitting extraordinary collection actions before reasonable efforts to determine eligibility.</p>
${
  hospitalRows
    ? `<table><thead><tr><th>Hospital</th><th>Free care ≤ (% FPG)</th><th>Discount ≤ (% FPG)</th><th>Collection actions permitted before eligibility is checked</th><th>Policy link (as filed)</th></tr></thead><tbody>${hospitalRows}</tbody></table>`
    : ""
}
${
  priceRows
    ? `<h2>Posted cash prices for common services (${priced.length} sampled hospitals)</h2>
<table><thead><tr><th>Service</th><th>Hospitals</th><th>Cash-price range</th><th>High ÷ low</th></tr></thead><tbody>${priceRows}</tbody></table>
<p><small>From hospital machine-readable standard-charge files. Posted prices are not what a given patient owes.</small></p>`
    : ""
}
<h2>Suggested outreach questions</h2>
<ul>
<li>Which residents with collection notices were screened for hospital financial assistance before the account was sent to collections?</li>
<li>Do local hospitals put their financial-assistance policy notice on bills, and is it translated for the community’s main languages?</li>
<li>For “debt was paid” disputes, can the provider supply an itemized ledger showing the payment and any reversal?</li>
<li>Which collectors appear most often locally, and do they accept validation requests and supporting documents by mail and online?</li>
</ul>
<h2>Limits</h2>
<p class="note">CFPB complaints are not a statistical sample and complaint volume reflects awareness of the CFPB as well as problems.
Complaints usually name collectors, not hospitals; hospital information is context, not attribution.
Schedule H answers are self-reported filings, linked to CMS hospitals by ZIP code and name, and may be out of date.
County placement uses ZIP-to-county approximations. Sources: CFPB Consumer Complaint Database; U.S. Census Bureau ACS 2020–2024;
CMS Hospital General Information; IRS Form 990 e-file (Schedule H).</p>
</body></html>`;
}

export function downloadBriefing(atlas: Atlas, row: StateRow) {
  const url = URL.createObjectURL(
    new Blob([briefingHtml(atlas, row)], { type: "text/html" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `not-my-debt-${row.state_abbr.toLowerCase()}-advocate-briefing.html`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
