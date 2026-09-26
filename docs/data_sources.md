# Research data and reproducibility

Not My Debt uses real CFPB complaint data to measure reported medical-debt problems and inspect the language of historical complaints. It uses separate synthetic document bundles to demonstrate evidence reconciliation. The complaint corpus contains no paired EOB, provider bill, payment receipt, and collection-notice bundles.

## Official sources

1. [CFPB Consumer Complaint Database](https://www.consumerfinance.gov/data-research/consumer-complaints/) and its [field reference](https://cfpb.github.io/api/ccdb/fields.html). The database is not a statistical sample, and complaints do not establish wrongdoing.
2. [2025 medical-debt API aggregation](https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/?size=3&date_received_min=2025-01-01&date_received_max=2025-12-31&product=Debt+collection%E2%80%A2Medical+debt). The hierarchical `product=Debt collection•Medical debt` filter is required. A separate `sub_product=Medical debt` parameter was tested and silently ignored. The refresh verifies that all sampled records match both product and sub-product before accepting an API response.
3. [Historical narrative archive index](https://www.consumerfinance.gov/foia-requests/foia-electronic-reading-room/cfpb-consumer-complaint-database-narratives-archive/), specifically [January–February 2025 ZIP](https://files.consumerfinance.gov/f/documents/CCDB_Export_9_January_2025_through_February_2025.zip). Only this single ZIP is downloaded: 75,475,199 compressed bytes; one 491,908,736-byte CSV. The refresh caps downloads at 90 MB, expanded CSV size at 600 MB, and checks the pinned SHA-256 `11c18bb0973eed8f5e4f66e2979346af0671a3aefcb5a6b9eec73009d53cff64`.
4. [CFPB narrative-publication change, August 14, 2026](https://www.consumerfinance.gov/about-us/newsroom/the-cfpb-to-cease-discretionary-publication-of-complaint-narratives-and-visualizations/). The current API does not supply complaint narratives. We do not treat `has_narrative=true` as a working filter. Historical text comes from the archive, not from the current API.

Exact retrieval timestamps, source byte counts, local input hashes, and the generated JSON hash are recorded in `data/research/source_manifest.json`. The generated artifact is `data/research/research.json`; it contains its own scope, methods, source links, patterns, and caveats. No keys or paid services are required for the research refresh.

## Observed data

The annual API query returned **8,843** medical-debt collection complaints received in 2025. Of these, **3,809** were categorized by consumers as attempts to collect debt not owed: 2,245 “Debt is not yours,” 1,005 “Debt was paid,” 404 identity-theft complaints, and 155 bankruptcy-discharge complaints. These are complaint categories, not independently established facts or distinct people.

The separate January–February archive scan counted **811,019** total rows and retained **1,644** medical-debt collection complaints. **819** had nonempty narratives (**49.82%**). Whitespace/case normalization and SHA-256 hashing found **7** duplicate narratives, leaving **812** unique texts. This is exact normalized-text deduplication; near-duplicate templates can remain. Of those unique narratives, 337 had a “debt not owed” issue: 192 not yours, 99 already paid, 38 identity theft, and 8 bankruptcy discharge.

Exploratory phrase matching among the 812 unique narratives found:

| Pattern | Unique narratives matching |
|---|---:|
| Already-paid language | 41 |
| Insurance / coverage language | 178 |
| Identity / recognition language | 57 |
| Verification / documentation language | 244 |
| Amount / duplicate-billing language | 6 |

| Document mentioned | Unique narratives matching |
|---|---:|
| Bill / invoice / statement | 274 |
| Receipt / payment proof | 43 |
| Collection / validation notice | 36 |
| Explanation of benefits | 5 |

The exact regular expressions are included in the JSON and in `src/not_my_debt/research.py`. Patterns overlap, so bar heights cannot be added into a total. A mention may describe a requested, missing, or disputed document; it does not mean that document was supplied or available. Negation and context are not resolved. These narrow keyword rules are not trained or validated classifiers. For example, the already-paid rule matches fewer narratives than the consumer-selected “Debt was paid” label.

The period, available narrative subset, and denominator must remain visible in charts. The annual API and two-month archive use different windows and extraction dates. Missing narratives and complaint submission behavior create selection bias. We do not estimate general incidence, recovered money, resolution success, invalid-debt probability, or causal impact from these counts.

## Refresh

From the project root:

```bash
python scripts/refresh_research.py
```

This fetches a small API response, downloads the one archive only if absent, and scans it without expanding the CSV to disk. Full extracted narratives remain in ignored `data/raw/medical_narratives.jsonl`; only aggregate JSON and provenance are committed. No individual narrative excerpts or medical details are republished in the app artifact.

To reproduce from local cached inputs without network:

```bash
python scripts/refresh_research.py --reuse
```

Or supply the archive and cached API response explicitly:

```bash
python scripts/refresh_research.py --archive /path/to/CCDB_Export_9_January_2025_through_February_2025.zip --api-cache /path/to/medical_2025_api.json
```

A changed archive hash stops the run for source inspection. Regenerating the artifact changes generation timestamps even when the substantive counts stay identical. Cached API inputs retain their recorded retrieval timestamp, or their filesystem modification time if no metadata sidecar exists; they are not presented as a fresh API retrieval.

## What is and is not evaluated

Automated tests check filtering, missing-text handling, deduplication before counting, overlapping document mentions, archive integrity enforcement, and arithmetic consistency of committed denominators. They do not establish clinical, legal, classifier, or real-patient document accuracy. No human-reviewed corpus, model benchmark, or real-world outcome evaluation is claimed. Synthetic reconciliation fixtures and any model extraction evaluation must be described separately from this research analysis.
