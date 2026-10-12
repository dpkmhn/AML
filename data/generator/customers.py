"""Build the 200 customers. Keys starting with `_` are generator traits, never loaded."""

from __future__ import annotations

from datetime import date
from typing import Any

from data.generator.common import ADDRESS_AREAS, MERCHANTS, Ctx, country_name

Customer = dict[str, Any]

OCCUPATIONS = {
    "salaried": ["Software engineer", "Accountant", "Nurse", "Teacher", "Sales executive",
                 "Civil engineer", "HR officer", "Marketing manager", "Pharmacist",
                 "Customer service agent", "Project manager", "Cabin crew", "Bank officer",
                 "Architect", "Logistics coordinator", "Doctor"],
    "business": ["Owner, grocery store", "Owner, restaurant", "Owner, general trading company",
                 "Owner, salon", "Owner, mobile phone shop", "Owner, IT consultancy",
                 "Owner, textile trading", "Owner, auto spare parts", "Owner, cafe",
                 "Owner, laundry", "Owner, perfume shop", "Owner, travel agency"],
    "student": ["University student", "Postgraduate student", "College student"],
    "retiree": ["Retired engineer", "Retired teacher", "Retired government employee",
                "Retired banker", "Retired military officer"],
}
CASH_INTENSIVE = {"Owner, grocery store", "Owner, restaurant", "Owner, salon",
                  "Owner, mobile phone shop", "Owner, cafe", "Owner, laundry",
                  "Owner, perfume shop", "Owner, auto spare parts"}

EXPECTED_ACTIVITY = {
    "salaried": "Monthly salary in; rent, card spending and occasional remittances out",
    "business": "Customer payments in by transfer and some cash; supplier, rent and payroll out",
    "student": "Monthly family support in; small card spending out",
    "retiree": "Monthly pension in; low card spending; rare larger transfers",
}
UNIVERSITIES = ["University of Dubai", "Middlesex University Dubai", "American University in Dubai",
                "Heriot-Watt University Dubai", "Amity University Dubai"]


def build_customers(ctx: Ctx) -> list[Customer]:
    cfg = ctx.cfg
    segs: list[str] = []
    for seg, spec in cfg["segments"].items():
        segs += [seg] * spec["count"]
    order = ctx.rng.permutation(len(segs))
    segs = [segs[i] for i in order]
    n = len(segs)

    # Exact risk counts, shuffled; PEPs are drawn from the high-risk customers.
    mix = cfg["risk_mix"]
    n_high, n_med = round(n * mix["high"]), round(n * mix["medium"])
    risks = ["high"] * n_high + ["medium"] * n_med + ["low"] * (n - n_high - n_med)
    risks = [risks[i] for i in ctx.rng.permutation(n)]
    high_idx = [i for i, r in enumerate(risks) if r == "high"]
    pep_idx = {high_idx[i] for i in ctx.rng.choice(len(high_idx), cfg["pep_count"], replace=False)}

    nats = list(cfg["nationalities"])
    weights = list(cfg["nationalities"].values())
    total = sum(weights)
    probs = [w / total for w in weights]

    customers = []
    for i, seg in enumerate(segs):
        lo, hi = cfg["segments"][seg]["income"]
        income = round(ctx.uniform(lo, hi) / 500) * 500
        nat = ctx.choice(nats, p=probs)
        c: Customer = {
            "customer_id": f"CUS-{i + 1:04d}",
            "full_name": ctx.person_name(nat),
            "segment": seg,
            "occupation": ctx.choice(OCCUPATIONS[seg]),
            "declared_monthly_income_aed": float(income),
            "expected_activity": EXPECTED_ACTIVITY[seg],
            "risk_rating": risks[i],
            "is_pep": i in pep_idx,
            "nationality": nat,
            "account_opened": ctx.day_between(date(2016, 1, 1), date(2025, 12, 31)),
            "kyc_notes": "",
        }
        _add_traits(ctx, c)
        c["kyc_notes"] = _base_kyc_note(ctx, c)
        customers.append(c)
    return customers


def _add_traits(ctx: Ctx, c: Customer) -> None:
    """Recurring counterparties: real accounts repeat the same few payees."""
    seg, nat = c["segment"], c["nationality"]
    abroad = nat if nat != "AE" else None
    c["_merchants"] = [MERCHANTS[j] for j in
                       ctx.rng.choice(len(MERCHANTS), ctx.randint(3, 8), replace=False)]
    c["_family"] = (ctx.person_name(nat), abroad or "AE")
    c["_area"] = ctx.choice(ADDRESS_AREAS)
    c["_noise"] = None
    c["_quiet"] = False  # set by dormant scenarios: no normal activity
    if seg == "salaried":
        c["_employer"] = ctx.company_name()
        c["_salary_day"] = ctx.randint(25, 28)
        c["_pays_rent"] = ctx.chance(0.7)
        c["_rent_day"] = ctx.randint(1, 5)
        c["_landlord"] = ctx.person_name(ctx.choice(["AE", "IN", "PK", "LB"]))
        c["_remits"] = abroad is not None and ctx.chance(0.6)
    elif seg == "business":
        c["_company"] = ctx.company_name()
        c["_cash_intensive"] = c["occupation"] in CASH_INTENSIVE
        c["_suppliers"] = [ctx.company_name() for _ in range(ctx.randint(3, 6))]
        c["_supplier_days"] = [ctx.randint(5, 28) for _ in c["_suppliers"]]
        c["_clients"] = [ctx.person_name(ctx.choice(["AE", "IN", "PK", "EG", "PH", "GB"]))
                         if ctx.chance(0.6) else ctx.company_name()
                         for _ in range(ctx.randint(15, 60))]
        c["_landlord"] = ctx.company_name("Real Estate LLC")
        c["_rent_day"] = ctx.randint(1, 5)
    elif seg == "student":
        c["_family_day"] = ctx.randint(1, 10)
        c["_university"] = ctx.choice(UNIVERSITIES)
        if nat == "AE":
            c["_family"] = (c["_family"][0], "AE")
    elif seg == "retiree":
        c["_pension_day"] = ctx.randint(1, 3)
        c["_pension_payer"] = ("General Pension and Social Security Authority"
                               if nat == "AE" else f"Pension authority of {country_name(nat)}")
        c["_pension_country"] = "AE" if nat == "AE" else nat


def _base_kyc_note(ctx: Ctx, c: Customer) -> str:
    review = ctx.day_between(date(2024, 1, 1), date(2026, 3, 31)).strftime("%b %Y")
    seg = c["segment"]
    if seg == "salaried":
        note = f"Employed by {c['_employer']}; salary certificate on file. Lives in {c['_area']}."
        if c["_remits"]:
            note += f" Sends occasional remittances to family in {country_name(c['nationality'])}."
    elif seg == "business":
        note = (f"Sole owner of {c['_company']}; trade licence on file. "
                f"Shop in {c['_area']}.")
        if c["_cash_intensive"]:
            note += " Business takes card and cash sales."
    elif seg == "student":
        note = (f"Student at {c['_university']}; supported by family "
                f"({c['_family'][0]} in {country_name(c['_family'][1])}).")
    else:
        note = f"Receives pension from {c['_pension_payer']}."
    if c["is_pep"]:
        note += " PEP: close relative of a senior public official. EDD completed."
    elif c["risk_rating"] == "high":
        note += " Rated high risk at onboarding; EDD completed."
    return f"{note} Last CDD review {review}."
