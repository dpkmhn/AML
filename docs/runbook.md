# Runbook: operating and changing the copilot

For the team that runs the copilot after handover. The [README](../README.md) covers setup and
architecture; this page covers what to watch, how to change things safely, and what to do when
something goes wrong. Commands are for PowerShell from the repo root.

## The one rule

**No change reaches analysts until the golden-set evaluation passes the release gate.** This
covers a new model, a new prompt version, a threshold edit, a new typology and guidance
updates. Rules, prompts and thresholds are versioned files, so every change is a reviewable
diff and every rollback is a revert.

### Release gate

```powershell
uv run pytest                                        # offline, about a minute
uv run python -m evals.run_eval --tag <change-name>  # 60 golden alerts, ~10 min, ~$0.20
```

The eval writes `evals/results/<date>_<tag>.json` and adds a row and confusion matrix to
[evals/results/summary.md](../evals/results/summary.md). Compare it with the latest reference
row (`v1-reference`).

| Metric | Gate | Reference |
| --- | --- | --- |
| Missed escalations | **0. Hard stop, no exceptions** | 0 in all 16 recorded runs |
| Injection traps failed | **0 of 4. Hard stop** | 0 of 4 |
| Route accuracy | No worse than 53 of 60 | 53 to 56 of 60 |
| False escalations | 2 or fewer | 0 to 2 |
| Cost per alert | Within 1.5× of $0.0025 | $0.0025 |
| p95 latency | 90 s or less | 61.9 s |

The model runs at its default temperature, so identical runs differ by up to 2 cases. If a
result sits on a gate, run it again before deciding. A missed escalation is never noise: one
blocks the change until it is explained and fixed.

## What to monitor

Every node writes an `audit_log` row with its model, prompt version, tokens and latency, and
every case stores the recommended route, the analyst's final route and any override reason.
The queries below run against those two tables (`kind = 'case'` excludes eval runs). Connect
with `docker compose exec db psql -U postgres -d aml`.

| Signal | Why it matters | Act when |
| --- | --- | --- |
| Overrides to Escalate | The copilot recommended Close or Needs more info and the analyst escalated: the live proxy for a missed escalation | **Any.** Review the same day (see incidents) |
| Override rate | Analysts disagreeing with the copilot | Above 15% in a week, or rising for 2 weeks |
| Cost per alert | Spend, and a sign of retries or prompt bloat | Above $0.004 for a day |
| p95 time to review-ready pack | Analysts waiting | Above 90 s for a day |
| Failed or stuck cases | Cases with no recommendation | Any older than 1 hour |
| Flagged references (R6) | Injection attempts | Any: confirm the case escalated |

**Overrides to Escalate (check daily):**

```sql
SELECT case_id, alert_id, recommended_route, reviewer, override_reason, decided_at
FROM cases
WHERE kind = 'case' AND final_route = 'escalate' AND recommended_route <> 'escalate'
ORDER BY decided_at DESC;
```

**Override rate by week:**

```sql
SELECT date_trunc('week', decided_at) AS week,
       count(*) AS decided,
       round(100.0 * avg((final_route <> recommended_route)::int), 1) AS override_pct
FROM cases
WHERE kind = 'case' AND decided_at IS NOT NULL
GROUP BY 1 ORDER BY 1 DESC;
```

**Cost per alert by day.** The prices are USD per 1M tokens for `gpt-6-luna`. Keep them in step
with [evals/prices.yaml](../evals/prices.yaml).

```sql
SELECT date_trunc('day', c.created_at) AS day,
       round(sum(a.tokens_in * 0.10 + a.tokens_out * 0.50) / 1e6 / count(DISTINCT c.case_id), 4)
         AS usd_per_alert
FROM cases c JOIN audit_log a USING (case_id)
WHERE c.kind = 'case' AND a.model IS NOT NULL
  AND a.step NOT IN ('analyst_review', 'draft_narrative', 'write_audit')
GROUP BY 1 ORDER BY 1 DESC;
```

**p50 and p95 seconds from alert to review-ready pack**, by summing the steps before the review:

```sql
WITH per_case AS (
  SELECT c.case_id, date_trunc('day', c.created_at) AS day, sum(a.latency_ms) / 1000.0 AS secs
  FROM cases c JOIN audit_log a USING (case_id)
  WHERE c.kind = 'case' AND a.step NOT IN ('analyst_review', 'draft_narrative', 'write_audit')
  GROUP BY 1, 2
)
SELECT day,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY secs) AS p50_s,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY secs) AS p95_s
FROM per_case GROUP BY 1 ORDER BY 1 DESC;
```

**Stuck cases**: created more than an hour ago with no recommendation:

```sql
SELECT case_id, alert_id, created_at FROM cases
WHERE kind = 'case' AND recommended_route IS NULL AND created_at < now() - interval '1 hour';
```

**Which model and prompt produced what.** Run this after a change, to confirm that only the
new versions are in use:

```sql
SELECT date_trunc('day', created_at) AS day, step, model, prompt_version, count(*)
FROM audit_log WHERE model IS NOT NULL
GROUP BY 1, 2, 3, 4 ORDER BY 1 DESC, 2;
```

`GET http://localhost:8000/health` returns the models and prompt version the API is running.

## Common changes

### Change the model

The model is configuration, not code. `MODEL_SMALL` runs the cases (`assess_case` and
`draft_narrative`); `MODEL_STRONG` runs the eval's narrative judge.

1. Add the new model's prices to [evals/prices.yaml](../evals/prices.yaml) and update
   `checked:`. The eval stops with an error if a model has no price.
2. Run the eval with the new model before you switch: set `MODEL_STRONG` to it and run
   `uv run python -m evals.run_eval --tag <model>-candidate --model strong`. To keep the judge
   unchanged instead, set `MODEL_SMALL` in a local `.env` and run with the default
   `--model small`.
3. If it passes the gate, set `MODEL_SMALL` in `.env` and restart the API:
   `docker compose up -d --build api`. Check `/health`, then the "which model" query.
4. Update the cost-per-alert query's prices.

Models that reject `temperature=0` fall back to their default temperature automatically
([app/llm.py](../app/llm.py)). Expect more run-to-run variation from those models.

**Changing the embedding model** also means changing `EMBED_DIM`. It must equal `vector(N)` in
[db/init/01_schema.sql](../db/init/01_schema.sql). Then rebuild the guidance index with
`uv run python -m app.rag.ingest` and run `scripts/check_retrieval.py` before the eval.

### Change a prompt

Prompts are never edited in place.

1. Copy the current version to the next number, for example
   `app/prompts/assess_case_v3.md` → `assess_case_v4.md`. `PROMPT_VERSION` selects both prompts
   the cases use, `assess_case` and `draft_narrative`, so create the new number for both, even
   if one of them does not change. The eval's judge prompt and the LLM-routing experiment's
   prompt have their versions fixed in code (`evals/judge.py`, `app/graph/nodes/review.py`).
2. Set `PROMPT_VERSION=4` in a local `.env`, run the tests and the eval, and record what
   changed and why in [evals/notes/fixes.md](../evals/notes/fixes.md).
3. If it passes, set `PROMPT_VERSION` in the deployed `.env` and restart the API. To roll back,
   set the old number again: old prompt files are never deleted.

### Tune a threshold

Every tunable number lives in [app/rules/thresholds.yaml](../app/rules/thresholds.yaml), with
a comment saying why it has its value.

- **Typology rules** (`structuring:`, `funnel:` and so on): scores ramp from 0.4 at `soft_*` to
  1.0 at `hard_*`. Run `uv run python scripts/check_rules.py` after an edit. The labelled
  typology must still score 0.4 or more in at least 20 of the 22 planted cases.
- **Routing** (`routing:`): `escalate_score` (0.7) and `high_risk_escalate_score` (0.4) decide
  R1 and R2; `min_close_confidence` (0.6) and `min_explained_share` (0.5) guard Close. Lowering
  any of these makes Close easier, so it needs compliance sign-off as well as the gate.
- **Monitoring** (`monitoring:`): the upstream alerting rules in the synthetic bank. A real
  bank's monitoring engine replaces these.

Then run the tests and the full eval.

### Add a typology rule

A typology is a name, a rule, thresholds, guidance and labelled cases. Using
`dormant_reactivation` as the pattern to copy, add the new name in each of these places:

| Step | Where |
| --- | --- |
| 1. Name | `TypologyName` and `TYPOLOGIES` in [app/schemas.py](../app/schemas.py) |
| 2. Features it needs | `Features` in `app/schemas.py`, computed in [app/rules/features.py](../app/rules/features.py) (deterministic, no LLM) |
| 3. Rule | A function in [app/rules/typologies.py](../app/rules/typologies.py) returning a `TypologyFinding` with a score from `ramp()`, the evidence transaction IDs and a plain-English `rule_explanation`; register it in `RULES` |
| 4. Thresholds | A new block in `thresholds.yaml` with `soft_*` and `hard_*` values and a comment on why |
| 5. Retrieval query | Add an entry to `build_query` in [app/rag/retrieve.py](../app/rag/retrieve.py) |
| 6. Guidance | `app/rag/guidance/typ_<name>.md` with front matter `doc_id`, `title`, `typology`, `version`, the same sections as the existing typology documents, then `uv run python -m app.rag.ingest` |
| 7. UI labels | The `Typology` union in [web/src/api.ts](../web/src/api.ts) and its label in [web/src/lib/format.ts](../web/src/lib/format.ts) |
| 8. Tests | Thresholds and edge cases in [tests/test_typologies.py](../tests/test_typologies.py) |
| 9. Eval cases | A planted case (`data/generator/inject.py`) and a benign look-alike (`data/generator/lookalikes.py`), labelled in `data/golden_set.jsonl`. Without both, the eval cannot show the rule catches the pattern without escalating innocent customers |

Then run `scripts/check_rules.py`, `scripts/check_retrieval.py`, the tests and the full eval.
Check the new typology's precision in the eval output: a noisy rule, as profile mismatch is
(precision 0.35), raises the work for every look-alike. Consider whether it belongs in
`routing.combination_excludes`.

**What routing does with it.** Nothing needs changing in
[app/rules/routing.py](../app/rules/routing.py). A strong unexplained score escalates (R1), and
Close still needs every fired typology explained with evidence (R4). Change routing only with
compliance sign-off.

### Update guidance documents

Edit the document in `app/rag/guidance/`, increase its `version:` and re-run
`uv run python -m app.rag.ingest`. Ingestion is safe to repeat: it updates chunks and removes
any the document no longer has. Then run `scripts/check_retrieval.py` and the eval: citation
accuracy depends on which chunks are retrieved.

## Incidents

**An analyst escalated a case the copilot recommended closing.** Treat this as a possible missed
escalation, the one error the system is designed never to make.

1. Run `uv run python scripts/replay_case.py <CASE-ID> --output` to see every step with its
   recorded output: the routing rule that fired (`decide_route`) and the evidence the assessment
   cited.
2. Decide which layer failed. Did a typology rule not fire (feature or threshold)? Did a quote
   or explanation pass the checks when it should not have ([app/validate.py](../app/validate.py))?
   Or did a routing rule close it when it should not have?
3. Add the alert's pattern to the golden set as a labelled case, fix the cause, and pass the
   gate before redeploying. Record it in `evals/notes/fixes.md`.
4. Until it is fixed, consider moving back one rollout phase (for example from prioritised queue
   to assisted).

**Cost or latency spike.** Run the "which model" query: has the model or prompt version changed?
Compare tokens per step with the eval's per-step figures. A larger prompt, a provider slowdown
or repeated validation retries (`assess_case` calls twice when checks fail) are the usual causes.

**The model API is down or refusing.** Cases fail before the review step and the API returns an
error; nothing is closed automatically. Analysts work affected alerts by hand. Once the provider recovers,
opening the case again from the queue runs it again: a case without a recommendation is
re-run, while one awaiting review or already decided is returned as it is.

**A flagged injection attempt (R6).** The case escalates by design. Check with `replay_case.py --output`
that the reference reached the model as quoted data and that the escalation reason names it.
Tell the financial crime team: an instruction in a payment reference is itself a red flag.

**A case is stuck in review.** The graph is checkpointed in Postgres under the case ID, so it
survives restarts. Resume it with
`uv run python scripts/review_case.py <CASE-ID> --reviewer <name> --route <route>`. An override
needs `--reason`.

## Rollback

| Change | Roll back by |
| --- | --- |
| Model | Set the previous `MODEL_SMALL` in `.env`, `docker compose up -d --build api` |
| Prompt | Set the previous `PROMPT_VERSION` in `.env`, restart the API |
| Threshold, rule or typology | `git revert` the commit, rebuild the API |
| Guidance | Revert the document, re-run `python -m app.rag.ingest` |

After any rollback, check `/health` and the "which model" query, and re-run the eval if the
change reached analysts.

## Access and data

- The copilot's tools use `copilot_ro`, which can only `SELECT`. Cases and audit rows are written
  through `copilot_rw`, which cannot touch customers or transactions
  ([db/init/02_roles.sql](../db/init/02_roles.sql)). Keep it that way: never point
  `DATABASE_URL_RO` at an admin user.
- The passwords in `.env.example` are for local development. Replace them, and keep `.env` out of
  version control.
- The audit log stores step inputs and outputs unmasked, including customer data. Restrict who
  can read it, and mask personal data before any production use.
- Narratives are internal. Nothing the copilot writes goes to the customer (tipping-off risk).
