# Reviewed reference data

## Complaint crosswalks

Raw labels are exact strings, including historical punctuation variants. The mappings
implement docs/04_features.md. `severity_tier` describes the reported issue, not a
finding of harm: 1 low, 2 medium, 3 high. The broad loss-mitigation bucket maps to 3;
sub-issues remain available for later refinement. Unrecognized labels fail ingestion
before replacing staging, so taxonomy changes require an explicit review.

`response_severity_tier` is a separate, provisional response-behavior scale:
1 relief, 2 explanation/no relief, 3 untimely. It never overrides issue severity,
and relief does not establish that the original complaint was less serious.
In-progress complaints remain in staging (needed for subsequent updates) but have
null response severity and `response_metrics_eligible=false`. Exclude them from
response metric numerators AND denominators. Legacy `Closed` is mapped to no_relief
per the project specification; do not infer more detailed outcomes from it.

Blank responses map to `unknown`, with null response severity and exclusion from
response metrics (one such mortgage row in the 2026-09-26 bulk export).

## Enforcement labels and parties (M1, 2026-09-26)

`enforcement_labels.csv` contains one reviewed row for each of the 386 CFPB
actions. `mortgage_related` means the action summary describes mortgage
origination, servicing, foreclosure/loan-modification relief, housing-credit
discrimination, mortgage referrals/settlement services, mortgage insurance, or
home-purchase financing (including contracts for deed). It describes the subject
of the public action, not an adjudicated violation. Product tags guide review;
the summary confirms the label. Being a mortgage lender or a bank is insufficient
when the action concerns a different product. Later dismissal does not erase a
filing event. `rationale` records the action-specific judgment.

Review was performed by Codex individually reading tags and summaries, not a
keyword labeling rule or an independent human review. Review provenance makes
that explicit. The SHA-256 hashes identify the exact summary and fuller available
caption (listing versus detail heading); changes force re-review before staging.
Unseen slugs, missing labels, unknown products and incomplete party reviews also
fail staging. Do not edit hashes alone to bypass a changed-source review.

Examples of decisions:

- ACI Worldwide / ACI Payments is **true** despite a Payments-only tag: its
  summary describes unauthorized mortgage-payment withdrawals.
- Harbour Portfolio / National Asset Advisors / National Asset Mortgage is
  **true** despite a Furnishing-only tag: the summary identifies contracts for
  deed used to finance home purchases.
- International Land Consultants and 3D Resorts Bluegrass are **false**:
  land-sale/development disclosures without identified mortgage-credit conduct.
- Monster Loans is **false**: the action concerns student-debt relief and misuse
  of credit reports; a mortgage-industry ban is a remedy, not the underlying product.
- GreenSky's general home-improvement consumer loans are **false** absent
  identified mortgage lending. A house transferred to evade a debt-collection
  judgment is also not enough to label an action mortgage-related.

`enforcement_parties.csv` is the reviewed splitting authority. It retains legal
suffixes and inline trade/former names as one party, splits named respondents,
and distinguishes `company`, `individual`, and `non_entity`. The latter means
**not an identifiable operating-company respondent**: unnamed affiliates,
`et al.`, government plaintiffs, and non-operating revocable relief trusts.
It does not assert that a trust lacks legal personality. Individuals and
non-entities are excluded from company matching. Some captions omit named
respondents behind `et al.`; these rows preserve that uncertainty, not a claim of
complete docket-level defendant enumeration. A summary-only addition identifies
its source explicitly. Heuristic splitting in `ews.resolve.parties` generates
review proposals; production staging consumes only the reviewed CSV.

`enforcement_product_crosswalk.csv` covers all 21 observed product tags and maps
to exact current or legacy CCDB product strings. `product_family` is a direct
family match; `contextual` is one-to-many and requires the underlying summary;
`context_only` has no standalone CCDB product (Fair Lending). Deposits maps to
Checking or savings account and legacy Bank account or service. Contextual tags
such as Payments or Debt Relief never mechanically determine `mortgage_related`.

Reproduce with `make enforcement`; replay with
`make enforcement ENFORCEMENT_ARGS=--offline`. Outputs, count definitions and the
initial feature cap are recorded in ADR-008. Company identity and panel eligibility
remain separate M2/M3 work, so action counts cannot serve as fitted-model event counts.

## Entity identity reviews (M2, 2026-09-26)

`entity_manual.csv` fixes stable entity IDs, types, FDIC charter membership and
holding-company anchors. `alias_manual.csv` overrides all automatic proposals on
exact `(source, raw_string)` keys and inclusive validity dates. Rejections and
unresolved decisions also override proposals. `hmda_lei_manual.csv` records the
reviewed reporter LEIs and their entity-linkage intervals; notably Flagstar's LEI
belongs to the predecessor before 2022-12-01 and NYCB thereafter.
`entity_relationships.csv` distinguishes a rename, a bank merger, a corporate
merger and an asset sale. Only mergers set a different successor. Historical
complaints are not rewritten to successor IDs. Ditech's asset-sale entry records
court approval, not a fabricated dissolution/closing date or universal successor.

These decisions were individually reviewed by **Codex**, not an independent
human. Names without a verified cross-source identifier remain identity-only
records, with null identifiers; they are not assigned to a similarly named bank.
The CFPB `Pending Company Match` routing placeholder is explicitly unresolved.
All 150 priority names have a decision, of which 149 are accepted. Human
adjudication remains outstanding. Do not replace the reviewer column merely to
make the human gate pass.

Run `make resolve` after complaint/enforcement staging exists. The first run
archives the complete active/inactive FDIC roster, relevant `/history` events,
2018–2023 HMDA panels and 2024–2025 transmittal sheets. Replay with
`make resolve RESOLVE_ARGS=--offline`; refetch with `RESOLVE_ARGS=--refresh`.
Archive hashes, JSON/ZIP content checks, pagination counts, and reviewed reference
validation precede publication. `--require-human-review` additionally requires
94% independent human complaint coverage and human review of all company parties.

The published `data/marts/crosswalk.csv` is intentionally one alias × identifier
observation per row. Never join complaints directly to that expanded table:
join `alias.parquet` by exact source/name and date, or use
`complaint_entity.parquet`. RSSD, LEI and HMDA identifier remain strings; blank,
zero and `-1` are missing. Modern HMDA identifiers are LEIs. Legacy IDs and the
headerless 2017 panel are deliberately not guessed into this modern crosswalk.
`identifier_year` describes the identifier observation's vintage, not public
availability. The reviewed `rssdhcr` is the modeling identity anchor; the
2024–2025 TS files do not verify current ownership. Financial membership and
release-time joins still need dated evidence in M3. Nonbanks and credit unions
have no FDIC charter/deposit denominator.

`match_review_queue.csv` includes 85–95 inclusive and ambiguous exact matches;
95 is conservatively queued. Scores above 95 with one best entity are proposals
marked `auto_accept`; they never count as manual coverage or enter the published
reviewed alias table. Unmatched/alternative proposals are in
`match_proposals.csv`. To accept a queue decision, add its evidence and exact
source spelling to the reviewed references, then rebuild.

See [the resolution report](../../docs/12_entity_resolution_report.md) for coverage,
identifier gaps, source decisions and remaining independent review.
