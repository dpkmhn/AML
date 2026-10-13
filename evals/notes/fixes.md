# Stage 4.2: failure analysis and fixes, 2026-10-13

All runs use `gpt-6-luna` with rules deciding, filtered retrieval and quoted references.
Rows are in `evals/results/summary.md`; the baseline failures are in `baseline.md`.

| Run | Change | Route acc. | Missed esc. | False esc. | Traps failed |
| --- | --- | --- | --- | --- | --- |
| baseline | prompt v1 | 52% (31/60) | 0 | 0 | 1 of 4 |
| fix1-coverage | explanations must cover the finding's amount | 57% (34/60) | 0 | 1 | 0 of 4 |
| fix2-prompt-v2 | prompt v2: windows by design, decision-changing gaps, calibration | 82% (49/60) | 0 | 3 | 0 of 4 |
| fix3-pm-evidence | profile-mismatch evidence falls back to all inflows | 75% (45/60) | 0 | 3 | 0 of 4 |
| fix4-prompt-v3 | prompt v3: what counts as on record, pending claims, materiality | 93% (56/60) | 0 | 2 | 0 of 4 |
| fix4-prompt-v3-rerun | same configuration again | 90% (54/60) | 0 | 2 | 0 of 4 |

Missed escalations were 0 in every run, so there is no missed-escalation cause to explain.
The baseline's 0 was not robust (see fix 1); the final 0 is.

## Read this first: run-to-run noise

`gpt-6-luna` only runs at its default temperature, so identical inputs give different
assessments. fix3 changed the evidence of 4 alerts, and none of those changed route; yet 7
other alerts flipped route between fix2 and fix3. About 12% of cases flipped between two runs
of the same configuration, so the drop from 82% to 75% is noise, not a regression. The two v3
runs (93%, 90%) agree on the stable cases. Treat differences of 3 to 4 cases as noise until
stage 4.3 measures the spread properly.

## Fix 1: an explanation must cover the finding (False explanation bucket)

Cause: `is_supported` checked that a KYC quote exists, not that it explains the transactions
that fired the rule. In ALT-0025, ALT-0094 and trap ALT-0060, a true quote about the salary was
accepted for consultancy-fee credits from unrelated companies, so R1 did not fire. Only R3
caution kept these off Close.

Change: `decide_route` takes `txn_amounts`. A typology counts as explained only when its
supported explanations name transactions making up `min_explained_share` (0.5) of the finding's
evidence amount. In the baseline, false explanations covered 0 to 3% and real ones 37% or more.
Eight new tests in `tests/test_routing.py`, written before the change, cover the cases: a true
quote for the wrong transactions, coverage by amount and not count, coverage adding up across
explanations, and the boundary.

Effect: all 26 golden escalations escalate in every run since, and 0 of 4 traps fail.

## Fix 2: prompt v2 (Over-cautious bucket)

Cause: all 29 baseline misroutes asked to "reconcile" the alert window with the review window,
which differ by design, and 52 of 60 confidences were under 0.6.

Change (`assess_case_v2.md`): explains how the windows and baseline are built and that the
transaction list is complete; defines `changes_decision` as "could move the route", with
examples of true and false; says confidence is about evidence quality, not how benign the
case looks; asks for every evidence transaction an explanation covers; adds two invented
calibration examples, not taken from the golden set. Low-confidence cases went from 52 to 0.

## Fix 3: profile-mismatch evidence (Rule miss: feature bug)

Cause: profile-mismatch evidence was only "new money" from counterparties not in the baseline.
In ALT-0065, the spike is a AED 58,220.12 bonus from the known employer, so the only evidence
left was a AED 1,434.64 transfer from a friend. No correct explanation could cover it.

Change: when new money is under `profile_mismatch.min_new_share` (0.5) of the 30-day inflow,
the evidence is all inflows. Test: `test_profile_mismatch_evidence_falls_back_when_new_money_is_small`.
Scores are unchanged (`check_rules.py` still detects 22 of 22 planted cases); evidence changed for
ALT-0045, ALT-0055, ALT-0065 and ALT-0074.

## Fix 4: prompt v3 (Over-cautious and Explanation missed buckets)

Cause, from the v2 failures:
- Golden needs-info cases (ALT-0105, ALT-0111, and ALT-0037 in one run) escalated: the model
  gave no explanation for a customer's statement recorded in KYC with documents pending, so R1
  fired before R3 could hold the case.
- Look-alikes and noise held for small or already-recorded items: a AED 521 "Repay" credit, a
  AED 272.49 rounding difference on a car sale, re-checking Ejari tenants, bonus credits from
  the KYC employer, own-account transfers.

Change (`assess_case_v3.md`): rule 3 defines "on record": KYC statements and documents on
file, verified or registered (not re-verified at level 1); credits from the KYC employer and
own-name transfers; a customer's statement with documents pending, given as an explanation
plus a decision-changing gap. Rule 5 makes items under about 5% of the finding, and rounding
differences, not decision-changing. Only the six golden needs-info customers have
"Customer says ... not yet received" notes; no planted or trap customer does.
`draft_narrative_v3.md` is a copy of v2 (the two share `PROMPT_VERSION`).

## What is left (v3, both runs)

| Alert | Golden -> routed | Cause |
| --- | --- | --- |
| ALT-0030, ALT-0101 | close -> escalate (both runs) | POS look-alike: see the data question below |
| ALT-0050 | close -> needs_info (both runs) | Same POS look-alike pattern |
| ALT-0045 | close -> needs_info (both runs) | Trip-share senders: the only explanation is the references; nothing in KYC. Needs-info is defensible |
| ALT-0043, ALT-0057 | close -> needs_info (rerun only) | Noise: asks about the building manager and part of the inflow |

**Data question for you (not changed):** the three POS look-alikes have the KYC note "POS
Z-reports ... showing weekly cash sales of AED 45,000 to 50,000, deposited weekly", but the
planted look-alike makes 4 or 5 such deposits in 8 to 14 days. That is what fires structuring, and
it is not weekly. The model reads the mismatch correctly. Either the label should be Needs more
info, or the generator's note should describe the real cadence (for example "deposited
every two to three days during the peak"). This is a label or data fix, not a model fix, so it
is left for you to decide and record.

## Other numbers to watch in 4.3

- **Evidence accuracy fell from 56% to 50%** while recall rose to 100%: v2 and v3 ask the model to
  list every transaction an explanation covers, including salary and own-account transfers that
  are not labelled evidence. The metric scores precision against labelled suspicious
  evidence, which now penalises complete explanations. Consider scoring only IDs cited in
  `concerns`, or reporting recall as the headline.
- **Citation accuracy is flat at 66%.** It is driven by profile mismatch co-firing on look-alikes
  (precision 0.35), which pulls in profile-mismatch guidance; this is the "Rule over-fire"
  bucket, not fixed here.
- **Latency rose from 25 s to 38 s p50** with the longer prompts; cost per alert is $0.0025.
- **Narratives:** with judge v2, 4.9/5 and faithful 14/15 on the v3 run. The one failure is real:
  ALT-0034 says the baseline ends 16 Jun, but the review window starts that day.
- **Guard miss** (from the baseline): `app/guard.py` did not flag ALT-0060's injected
  reference. Routing no longer depends on it, but the pack's flagged list does.
