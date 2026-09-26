# Complaint crosswalks

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
