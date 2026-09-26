# 11 · Presentation Plan

## The one question

> Can public mortgage complaints help consumer-protection analysts decide which companies to look at first?

**Audience in the story:** an analyst with limited time. **Our answer, from the backtest:** yes, but the useful signal is plain complaint volume, not the unusual-change score we built. The dashboard shows what changed and why, and it is honest about which signal actually preceded enforcement.

## Headline claim (say this, nothing stronger)

"We built a mortgage complaint monitor and tested, without look-ahead, whether unusual complaint changes anticipated CFPB enforcement from 2016 to 2023. They did not: ranking companies by plain 12-month complaint volume caught half of the later-enforced companies in its top 20; our change score caught 4%, below a random ranking's 11%. Enforcement landed on persistently high-volume servicers, not on sudden changes. The dashboard makes both views visible, with their limits."

### Never say

- "We predict enforcement," "early warning works," or "flagged N months early" as a general claim.
- That any live-ranked company is likely to be enforced or did anything wrong.
- That size-normalized rates were tested. The size-normalized baseline is unavailable at every historical cutoff.
- That our models beat baselines, or that B/C beat volume. Model C matches volume's recall in a few settings, on fewer cutoffs; don't cherry-pick those.

## Numbers we use (all primary window, all filings, 12-month horizon)

| Fact | Value | Source |
|---|---|---|
| Mortgage complaints | 461,350 (Dec 2011–Sep 2026) | README |
| CFPB enforcement actions | 386 (2012-07-17 → 2025-08-21), none since | README |
| Backtest design | 8 annual cutoffs (Jan 2016–Jan 2023), ~110 companies each, 13 first-filing events | `reports/score_snapshots.csv.gz` |
| Recall@20: "of companies later enforced, share in the top 20" | Volume 50% · Model A 4% · random 11% | `reports/backtest_2026-09-26.md` |
| Precision@20 | Volume 3.8% (under 1 in 20; filings are rare) · Model A 0.6% | same |
| PR-AUC difference vs volume | A −0.10 [−0.34, 0.06] (not distinguishable); B −0.14 [−0.50, −0.05] and C −0.17 [−0.50, −0.12] (credibly worse) | same, line 48 |
| Top-20 overlap, Model A vs volume | 0–2 of 20 companies at every cutoff | `score_snapshots.csv.gz` |
| Event-aligned chart at filing | Enforced companies' complaints ≈3.3× their level 48 months earlier vs ≈1.65× for matched peers; 11 pairs, intervals overlap | dashboard `event_aggregate` |

Note: the "prior action" baseline is mechanically identical to volume (only 2 of 878 scored rows had a prior action), so don't present it as separate evidence.

## Chosen examples

| Role | Company · cutoff | What happened | Why we show it |
|---|---|---|---|
| **Model A's hit** | Planet Home Lending · Jan 2016 and Jan 2017 | Model A ranked it #3 (2016) and #1 (2017); CFPB filed 2017-01-31. Volume ranked it #46 (2017). | What the change score is for: it surfaced a mid-size company volume ignored. Be honest: the 2016 flag came 13 months early, which counts as a false alarm under our 12-month rule, and this is one company. |
| **Model A's miss / volume's hit** | Ocwen and Nationstar · Jan 2017 | Volume ranked them #2 and #3. Model A ranked them #108 and #109 of 114, because their complaints were *falling* versus their own history (self-z ≈ −1.9). Filed 2017-04-20 and 2017-03-15. | The core finding in one picture: enforcement followed persistent volume, not change. |
| **False alarm** | DHI Mortgage · Jan 2016 | Model A's #1, on 9 complaints (self-z 6.5). No filing. | Small bases produce extreme change scores; this is why the live monitor now hides companies under 20 complaints by default. |
| **Entity resolution** | Ocwen | "Ocwen Financial Corporation" (complaints), "Ocwen Financial Corp." (enforcement) and its later name "Onity Group Inc." resolve to one entity. Ocwen Loan Servicing and Ocwen Mortgage Servicing remain separate entities: parent chains were deferred. | Shows the hard data work, and an honest gap, in one company. |

## Narrative arc (7 minutes)

1. **Question and audience (30 s).** An analyst faces over 20,000 mortgage complaints a year across hundreds of companies. Where do they look first? We asked whether *unusual changes* in complaints point to future enforcement.
2. **Data and the hard part (1 min).** 461k mortgage complaints, 386 enforcement actions, FDIC and HMDA exposure data. Entity resolution: Ocwen's complaint name, enforcement name and later name (Onity Group) resolve to one company. A no-look-ahead backtest: every score uses only data published before the cutoff.
3. **The example that motivated us (45 s).** Planet Home Lending: our change score put it at #1 a month before its 2017 filing, when volume had it at #46. Pause: "That's one company. Did it generalize?"
4. **The result (1 min 30 s).** Same cutoff, Jan 2017: Ocwen and Nationstar, #2 and #3 by volume, #108 and #109 by our score; both enforced within four months. Pooled over eight years: volume's top 20 caught 50% of later-enforced companies, ours 4%, random 11%. Our two statistical models did no better. Enforcement landed on persistent high-volume servicers. The event-aligned chart agrees directionally (enforced companies' complaints climbed about 3× vs about 1.6× for peers) but with 11 pairs the intervals overlap.
5. **Demo (2 min).** Click path below. Frame the change monitor as "what changed and why," with volume one click away as the historically stronger lens.
6. **Limitations (45 s).** 13 enforcement events: every estimate is wide. No point-in-time size data, so we can't separate "big" from "bad." CFPB uses complaints in supervision, so volume may partly mirror regulatory attention. No CFPB filings since Aug 2025, and narratives stopped being published in Aug 2026. False alarms like DHI.
7. **Next (15 s).** State regulator and multi-agency labels (more events), point-in-time servicing exposure for real size normalization, other products.

## Demo click path

Rehearse on the deployed app; keep screenshots and a recording for every step.

1. **Complaint change monitor** (default: unusual change, ≥20 complaints). Read the caption aloud. Point at the "Top 3 drivers" column. Switch **Rank by → 12-month complaint volume**: "This is the list that historically did best, and it's the big servicers every analyst already knows."
2. Switch back and click **MidFirst Bank** → **Company detail**: complaints versus the peer band, issue mix by severity, bank financial panel, "why flagged" drivers. Say "complaints rose relative to its own history," nothing more.
3. **Enforcement timeline** → **PLANET HOME LENDING, LLC**: shaded top-20 windows before the 2017-01-31 filing. Then **Ocwen Financial Corporation**: no shading. Scroll to the event-aligned aggregate.
4. **Backtest results** (primary / include / 12): read the headline. In "Top 20 at a historical cutoff" pick **2017-01-01**: model **A** shows Planet Home highlighted; switch to **raw_count** to show Ocwen and Nationstar highlighted.
5. **Limitations**: one sentence, then close.

## Rubric mapping (confirm against the official rubric)

| Criterion | Evidence we show |
|---|---|
| Impact | A deployed monitor analysts can use today; a reusable company crosswalk; a finding that tells regulators which cheap signal historically worked |
| Completeness | One-command pipeline; leakage-controlled backtest across 8 cutoffs × 3 horizons with baselines and cluster-bootstrap intervals |
| Innovation | Time-aware entity resolution; a rigorous test that reports a negative result instead of hiding it |
| Visualization | Change monitor, company timeline with pre-filing flags, event-aligned chart, backtest view with intervals |
| Presentation | One question, answered with evidence, counterexamples, and limits |

## Likely questions

- **"Why keep Model A if volume won?"** It answers a different question: what changed and why. The volume list is the same few giant servicers every year; the change view is for spotting emerging issues at everyone else. We don't claim it predicts enforcement.
- **"Isn't volume just company size?"** Probably, largely. We couldn't test size-normalized rates because point-in-time exposure data isn't available for the historical cutoffs. That's our top next step.
- **"Is 13 events enough?"** No, not for fine distinctions. That's why we report intervals and say Model A is not distinguishable from volume on PR-AUC. The recall gap (50% vs 4%) is large, but it rests on few events.
- **"Planet Home was flagged 13 months early; isn't that a success?"** Under our pre-set 12-month rule, it's a false alarm at the 2016 cutoff and a hit at 2017. We kept the rule rather than moving the goalposts.
