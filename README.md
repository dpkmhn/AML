# AML Alert Triage Copilot

Prepares an investigation pack for every transaction-monitoring alert so a level-1 AML analyst
can decide in minutes. Rules detect and route, the LLM gathers and explains, and the analyst
makes every final call. All data is synthetic; the bank (Falcon Digital Bank) is fictional.

## Quick start (Windows)

```powershell
uv sync
copy .env.example .env          # then fill in OPENAI_API_KEY and model names
docker compose up -d            # Postgres 16 + pgvector
uv run python -m data.generator.generate --reset
uv run python -m data.build_golden     # 60-alert golden set + data/out/golden_review.md
uv run python scripts/check_rules.py   # typology rules on the golden alerts
uv run python -m app.rag.ingest       # guidance documents -> guidance_chunks
uv run python scripts/check_retrieval.py
uv run python scripts/run_one.py ALT-0042   # runs a case up to the analyst review
uv run python scripts/review_case.py CASE-0001 --reviewer <name> --route escalate
uv run python scripts/replay_case.py CASE-0001   # the full audit trail
uv run python -m evals.run_eval --tag baseline   # golden set -> evals/results/summary.md
uv run pytest
```

## Layout

| Path | What lives there |
| --- | --- |
| `app/api/` | FastAPI routes: alerts, cases, review |
| `app/graph/` | LangGraph state, nodes, edges |
| `app/tools/` | Read-only SQL tools: profile, transactions, counterparties |
| `app/rules/` | Monitoring rules, typology rules, routing, `thresholds.yaml` |
| `app/rag/` | Guidance documents, ingestion, retrieval |
| `app/prompts/` | Versioned prompts (`<name>_v<N>.md`) |
| `data/generator/` | Seeded synthetic customers, transactions, scenarios |
| `evals/` | Evaluation runner, metrics, results |
| `ui/` | Streamlit analyst queue |
| `tests/` | Unit tests for rules and routing |

## Design notes

- Retrieval filters by typology first and ranks by vector similarity second. The corpus is
  about 50 section-level chunks, so there is no vector index: an exact scan is fast and its
  results are exact.
- The database container listens on host port 5433, so it can run beside a local Postgres.

## Conventions

- One commit per stage: `stage-N.N: <what is done>`.
- IDs: `CUS-0001`, `TXN-000001`, `ALT-0001`, `CASE-0001`, `CHK-<doc>-<n>`.
- Amounts in AED, `numeric(14,2)`; timestamps in UTC.
- Prompts are never edited in place; bump the version.
- All tunable numbers live in `app/rules/thresholds.yaml`.
- Ground-truth labels stay in `data/out/labels.jsonl` and `data/golden_set.jsonl`, never in the database.
