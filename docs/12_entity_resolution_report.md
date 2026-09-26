# M2 entity resolution · 2026-09-26

The published [crosswalk](../data/marts/crosswalk.csv) links exact CFPB complaint
and enforcement names to reviewed entities, FDIC CERTs and holding-company RSSDs,
and selected HMDA reporter LEIs. [Machine-readable coverage](../data/marts/resolution_report.json)
includes reference fingerprints, missing identifiers and unmapped complaint names.

| Review measure | Result |
|---|---:|
| Mortgage complaints | 461,350 |
| Complaints with explicitly reviewed accepted aliases | 433,967 |
| Reviewed complaint coverage | **94.0646%** |
| Top complaint names with a review decision | 150 |
| Top complaint names accepted | 149 |
| Distinct mortgage enforcement company-party strings | 121 |
| Mortgage enforcement company-party rows | 131 |
| Mapped company-party rows | **131/131 (100%)** |
| Independent human reviewed complaint coverage | **0% — outstanding** |

The reviewer is Codex, individually inspecting candidate identities and evidence.
This is not independent human adjudication. The project's numerical coverage gate
passes for these reviews; the independent human sign-off required by ADR-009 is
still outstanding. `make resolve RESOLVE_ARGS='--offline --require-human-review'`
correctly fails that additional gate before replacing any published artifact.
`Pending Company Match` is a routing placeholder, not a company; its 195 complaints
are deliberately unmapped. Named enforcement companies without a CCDB match have
their own entity, rather than borrowing a similar name's complaints. The 100%
measure covers named company respondents in the reviewed mortgage captions; it
excludes individuals, non-entities and unnamed defendants behind `et al.`.

The matcher ports the spike normalizer, adds `ASSN` expansion and `n/k/a`, preserves
internal generic words, and strips noise only from the tail. Exact normalized
keys retain every tied candidate. Fuzzy proposals use only first-token-blocked
`rapidfuzz.token_sort_ratio`. Scores 85–95 inclusive require review; ambiguous
exact keys also require review. A unique best score above 95 is an automatic
proposal, separately recorded and excluded from reviewed coverage. Exact raw
manual decisions and date intervals take precedence over all proposals.

The gold alias table includes explicit trade-name rows from the enforcement
captions. It rejects brand coincidences: Citizens Financial Group is CERT 57957,
First Citizens is the Raleigh institution (CERT 11063), and First American
Financial/Fidelity National Financial are title/insurance companies, not similarly
named FDIC banks. CMG Financial Services is retained as an identity-only firm;
its normalized collision with CMG Bancorp does not justify a bank or reporter link.

Bank charters are grouped by inspected FDIC `RSSDHCR`; active sibling charters
share the entity (TD: CERTs 18409 and 33947). Banks with no holding company retain
a standalone charter identity. Inactive roster ownership is not always predecessor
ownership: BBVA's inactive row names PNC, so its predecessor anchor uses a dated
2021 panel, and the PNC merger is a separate relationship. Flagstar's 2014 action
and pre-December-2022 complaints remain with its predecessor; later charter
complaints join NYCB. The 2026 roster has no holding company for the surviving
Flagstar bank; its historical NYCB anchor is explicitly dated evidence, not a
newly verified current ownership assertion.

Bank merger validation uses FDIC `/history` **OUT_CERT → SUR_CERT**, an exact
`EFFDATE` and merger description. It does not mistake `FRM_CERT` or acquired branch
records for a bank merger. The reviewed list covers Discover, SunTrust, CIT, BBVA,
TCF, Bank of the West, Hudson City, National City, Webster and BancorpSouth/Cadence.
Some bank legal merger dates differ from the holding-company closing date: the
crosswalk keeps the FDIC event's date, rather than silently substituting a news
announcement. For example, the archived SunTrust charter event is 2019-12-07.
The [FDIC API definitions](https://api.fdic.gov/banks/docs) document these datasets.

The hand-kept nonbank list distinguishes Nationstar's Mr. Cooper trade name,
[Ocwen's 2024 Onity parent rename](https://shareholders.onitygroup.com/news-releases/news-release-details/ocwen-financial-officially-rebrands-onitytm-group),
[Green Tree's 2015 surviving-entity rename to Ditech](https://www.sec.gov/Archives/edgar/data/1040719/000104071916000052/a101311fy2015q4.htm),
and [PHH's 2026 Onity Mortgage operating-company rename](https://www.onitygroup.com/Privacy).
PHH, Ocwen's operating subsidiaries and unrelated nonbank affiliates remain
separate operating identities. Ditech's [selected asset-sale approval](https://www.newrez.com/press-news/court-approves-nrz-asset-acquisition-of-ditech/)
is not a universal legal succession to Newrez; no dissolution date is invented.

The source archive contains 27,834 FDIC institutions (active and inactive), 217
relevant merger/name-change events, and 39,269 modern HMDA identity rows over
2018–2025. Reporter LEIs are explicitly selected, including charter-RSSD joins
for KeyBank, USAA, First Citizens, Trustmark and WaFd. The 2024–2025 transmittal
sheets supply LEIs, not refreshed ownership fields. Reporter RSSD is distinct from
holding-company RSSD; missing values and leading zeros are preserved correctly.
These are identity links, not origination/servicing exposure measures. No FDIC
financial denominator is assigned to a nonbank or credit union.

**ADR-012 decision: defer GLEIF and NIC.** There are 129 entities without a reviewed
HMDA LEI, including servicing-only firms, title/insurance/payment respondents,
legacy entities and parent-branded complaint names whose operating reporter link
is not yet established. These are recorded as gaps, not invented identifiers.
No remaining gap prevents the measured complaint/enforcement identity joins.
FDIC plus dated HMDA identities resolves the demonstrated bank gaps, including
Flagstar's historical ownership. GLEIF would not create a missing HMDA reporter or
servicing denominator; NIC is not needed merely because a nonbank RSSD is absent.
Reconsider either source if M3 establishes a specific required reporter or
historical ownership link that these sources cannot supply. Some parent-branded
nonbank identities still need a narrower operating-company link before HMDA
origination exposure can be used; their null identifiers must remain null meanwhile.

Reproduce with `make resolve RESOLVE_ARGS=--offline`. Outputs include a prioritized
review queue, top-150 review sheet, typed entity/alias/enforcement Parquet, and a
complaint-ID-to-entity Parquet table. Failed coverage/provenance/merger checks leave
published files intact. The expanded CSV has multiple identifier observations per
alias and must not be joined directly to complaints, which would multiply counts.
Use the exact dated alias table or complaint-entity Parquet instead.

Matcher evaluation is a leave-one-spelling-out check against the Codex-reviewed
aliases, not independent validation of those decisions. Precision/recall and
false positives at or above 95 appear in `resolution_report.json`. The original
seven spike false-positive pairs have explicit regression tests. The downstream
backtest comparison remains M4 work because no backtest is implemented yet.
