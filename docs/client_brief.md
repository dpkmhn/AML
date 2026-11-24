# Client brief and scoping note (mock)

> **This is a practice document.** Falcon Digital Bank is fictional, and so are the people, the
> volumes and the conversation below. I wrote the brief as a client would, then scoped it as I
> would for a real engagement, before building anything. The last section compares the scope with
> what the project delivered.

---

## Part 1: The brief

**From:** Head of Financial Crime Operations, Falcon Digital Bank (UAE)
**To:** AI engineering partner
**Subject:** Reducing our transaction-monitoring alert backlog

### Where we are

We are a digital retail bank with salaried, business, student and retiree customers. Our
transaction-monitoring system raises alerts on rules such as structuring, pass-through activity,
funnel accounts, dormant-account reactivation, high-risk jurisdictions and income mismatch.

Level-1 analysts review every alert. For each one they open the core banking system, the KYC
record and the transaction history, look for an explanation, and write a case note. Most alerts
turn out to be false positives, but every one still takes the full review.

### The problem

- **The backlog is growing.** Alert volume is up, and hiring has not kept pace. Our regulator
  expects alerts to be reviewed in a reasonable time, and an ageing backlog is itself a finding.
- **Reviews are inconsistent.** Two analysts can reach different conclusions on similar alerts,
  and case notes vary in quality, which makes second-line QA slow.
- **Most of the time goes on gathering, not judging.** Analysts tell us they spend most of each
  review collecting data before they can think about it.

### What we want

Something that prepares each alert for the analyst: the relevant customer and transaction facts,
whether there is a plausible explanation on record, what our own procedures say, and a draft case
note. The analyst should be able to decide in minutes.

### What we will not accept

1. **Nothing that should be escalated may be closed.** A missed suspicious case is a regulatory
   breach. We would rather review more alerts than miss one.
2. **No automated decisions.** A named analyst decides every alert. Compliance will not sign off
   anything that closes alerts on its own.
3. **Everything must be explainable and audited.** If the regulator asks why an alert was closed,
   we must show the evidence, the procedure followed and who decided.
4. **No customer-facing output.** Anything that could tip off a customer is out.
5. **Customer data stays under our control.** Hosting and model providers need approval from our
   information security team.

### Constraints

- We cannot share production data at the start. Work has to begin on representative data.
- Cost per alert has to stay small enough to make sense at our volume.
- Our team needs to be able to run and change this after handover.

---

## Part 2: Scoping note

**Prepared after a discovery call with Financial Crime Operations and Compliance.**

### My understanding

The bottleneck is data gathering and write-up, not judgement. The goal is a copilot that builds
the investigation pack and recommends a route, while the analyst keeps every decision. The one
error the bank cannot accept is a missed escalation, so the design optimises for that first and
for accuracy second.

### Scope

| In scope | Out of scope |
| --- | --- |
| Level-1 triage of monitoring alerts for six typologies | Changing the monitoring rules that raise alerts |
| An investigation pack: profile, transactions, counterparties, typology findings, cited procedures | Sanctions screening |
| A recommended route: Close, Needs more info or Escalate, with reasons | Filing suspicious transaction reports |
| A draft case note written from the analyst's decision | Network analysis across linked accounts |
| An analyst UI, an audit trail and an evaluation suite | Production hosting (the bank's platform team owns this) |

### Approach

- **Rules decide, the LLM explains.** Features, typology scores and the route are deterministic
  code, so they can be tested and audited. The LLM looks for benign explanations and drafts the
  narrative. It never picks the route.
- **Evidence is checked, not trusted.** A KYC quote must appear word for word in the notes, and
  every transaction ID must exist in the case. If a check fails, the case cannot close.
- **Human sign-off is built in.** The workflow pauses for the analyst. An override needs a reason,
  and every override is kept for review.
- **Payment references are treated as hostile.** Customers write them, so they reach the model as
  quoted data and instruction-like text is flagged.
- **Least privilege.** The copilot reads through a read-only database role.

### Success criteria (agreed before building)

| Measure | Target | Why |
| --- | --- | --- |
| Missed escalations | **0** on the labelled set | The bank's hard line |
| Injection attempts that change the outcome | **0** | Payment references are customer-written |
| Route accuracy | 85% or more | Enough to save analyst time |
| Evidence accuracy (cited transactions are the right ones) | 90% or more | Analysts and QA must trust the pack |
| Citation accuracy (procedures cited are the right ones) | 90% or more | Same |
| Cost per alert | Below USD 0.01 | Sensible at the bank's volume |
| Time to a review-ready pack | About a minute or less | Faster than gathering by hand |

### Data and evaluation plan

Production data is not available, so the work starts on **synthetic data shaped like the bank's**:
customers in the four segments, months of normal activity, planted examples of each typology, and
**benign look-alikes**. A look-alike is a customer whose activity matches a typology but has a
legitimate reason in KYC, for example an inheritance. Look-alikes are the hard part. They test
whether the copilot can tell the two apart without escalating innocent customers.

A labelled **golden set** of alerts, checked by hand, covers planted typologies, look-alikes,
alerts that need more information, and **prompt-injection traps** in payment references. Every
change to a prompt, model or threshold is re-scored against it before it ships.

### Rollout proposal

| Phase | What happens | Moves on when |
| --- | --- | --- |
| 1. Shadow | Runs on live alerts; analysts do not see it; outcomes compared afterwards | 0 missed escalations over an agreed volume |
| 2. Assisted | Analysts see the pack and recommendation, then decide | Review time drops, and override reasons are understood |
| 3. Prioritised queue | Likely escalations reach analysts first; a human still decides every alert | Compliance and model-risk sign-off |

### Risks and how they are handled

| Risk | Mitigation |
| --- | --- |
| The model invents evidence | Quotes and transaction IDs are checked against the case; failures block Close |
| Prompt injection through payment references | References quoted as data, flagged, and tested with traps in the golden set |
| Synthetic data does not reflect production | Shadow phase on real alerts before analysts rely on it |
| Results vary between runs | Repeated reference runs to measure the noise; gates allow for it |
| Model or provider changes | Model and prompt versions pinned and recorded on every audit row; eval re-run before any change |
| Personal data in logs | Flagged for masking before production use |

### Open questions for the bank

1. Which hosting and model providers does information security approve for customer data?
2. Who signs off each rollout phase, and on what volume of alerts?
3. Can second-line QA sample copilot-assisted closures during the shadow phase?
4. What case-note format does the regulator expect to see?

### Deliverables

- The copilot: API, analyst UI, and workflow with a human review step
- An evaluation suite and golden set, with results for every change
- A rollout plan and controls summary for Compliance
- A [runbook](runbook.md) for the team that runs it

---

## How the delivery compared with this scope

| Measure | Target | Delivered (run `v1-reference`, 60 alerts) |
| --- | --- | --- |
| Missed escalations | 0 | **0**, in all 16 recorded runs |
| Injection traps that changed the outcome | 0 | **0 of 4** |
| Route accuracy | 85% | **92% (55 of 60)** |
| Evidence accuracy | 90% | **51%, missed** |
| Citation accuracy | 90% | **66%, missed** |
| Cost per alert | Below $0.01 | **$0.0025** |
| Time to a review-ready pack | About a minute | **34.5 s p50, 61.9 s p95** |

The two misses are explained in the [README](../README.md#results). Cited transaction IDs always
exist in the case, so nothing is invented. The model cites about twice as many transactions as the
labels hold. Citation accuracy falls because the noisy profile-mismatch rule brings its own
guidance into cases labelled with another typology. Both would need fixing before a shadow phase.
