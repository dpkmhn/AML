"""Benign look-alikes: the same transaction shape as a typology, explained in kyc_notes.

These are the hard cases. The copilot must find the explanation in the profile, quote it, and
check that amounts, dates and counterparties match. Expected route: close.
"""

from __future__ import annotations

from datetime import date, timedelta

from data.generator.common import Ctx, country_name
from data.generator.customers import Customer
from data.generator.inject import Plant, _append_kyc, _fmt, dormant_history

CARS = ["Toyota Land Cruiser", "Nissan Patrol", "Range Rover Sport", "Mercedes G 500",
        "Lexus LX 600"]
BROKERS = ["Sarwa", "Interactive Brokers", "Emirates NBD Securities", "Mashreq Invest"]
OTHER_BANKS = ["Emirates NBD", "ADCB", "FAB", "Mashreq", "RAKBANK"]
TENANT_COUNTRIES = ["IN", "PK", "PH", "EG", "AE", "GB", "BD"]


def lookalike_structuring(ctx: Ctx, c: Customer, start: date) -> Plant:
    cid, d, deps = c["customer_id"], start, []
    takings = c["segment"] == "business" and c.get("_cash_intensive", False)
    for _ in range(ctx.randint(4, 5)):
        deps.append(ctx.txn(cid, ctx.ts_on(d, 9, 21), ctx.uniform(45500, 49500), "in", "cash",
                            reference="Shop takings" if takings else "Car sale"))
        d += timedelta(days=ctx.randint(1, 3))
    total = sum(t["amount_aed"] for t in deps)
    if takings:
        # the note describes the deposits as generated: every 1-3 days, AED 45,000 to 50,000
        _append_kyc(c, f"Seasonal peak: takings rise during Dubai Summer Surprises. Customer "
                       f"provided POS Z-reports for {start:%b %Y} showing peak cash sales of "
                       f"AED {round(total, -3):,.0f} over two weeks; takings are banked every "
                       f"one to three days, AED 45,000 to 50,000 at a time.")
        reason = "seasonal cash takings evidenced by POS reports"
    else:
        car, sold = ctx.choice(CARS), start - timedelta(days=ctx.randint(1, 3))
        _append_kyc(c, f"Sold {car} for AED {round(total, -3):,.0f} cash to a private buyer "
                       f"on {_fmt(sold)}; RTA transfer certificate and sale agreement on file. "
                       f"Proceeds deposited in instalments.")
        reason = "cash car sale documented in KYC"
    return Plant(deps, deps, "close", "structuring", notes=reason)


def lookalike_pass_through(ctx: Ctx, c: Customer, start: date) -> Plant:
    cid, name, d, txns = c["customer_id"], c["full_name"], start, []
    bank, broker = ctx.choice(OTHER_BANKS), ctx.choice(BROKERS)
    for _ in range(ctx.randint(2, 3)):
        amt = ctx.uniform(26000, 60000)
        t_in = ctx.ts_on(d)
        txns.append(ctx.txn(cid, t_in, amt, "in", "transfer", name, "AE",
                            f"Own transfer from {bank}"))
        txns.append(ctx.txn(cid, t_in + timedelta(hours=ctx.uniform(1, 30)),
                            amt * ctx.uniform(0.92, 0.99), "out", "transfer",
                            f"{name} - {broker} account", "AE", "Investment top-up"))
        d += timedelta(days=ctx.randint(6, 10))
    _append_kyc(c, f"Customer moves savings from own account at {bank} to own investment "
                   f"account with {broker}; account statements in customer's name on file, "
                   f"verified {_fmt(start - timedelta(days=20))}.")
    return Plant(txns, txns, "close", "pass_through", notes="own-account savings transfers")


def lookalike_funnel(ctx: Ctx, c: Customer, start: date) -> Plant:
    cid, txns, total = c["customer_id"], [], 0.0
    n = ctx.randint(10, 14)
    for _ in range(n):
        tenant = ctx.person_name(ctx.choice(TENANT_COUNTRIES))
        amt = round(ctx.uniform(3500, 7000), -2)
        total += amt
        d = start + timedelta(days=ctx.randint(0, 6))
        txns.append(ctx.txn(cid, ctx.ts_on(d), amt, "in", "transfer", tenant, "AE",
                            ctx.choice(["Rent", f"Rent {start:%b}", "Flat rent", "Monthly rent"])))
    txns.append(ctx.txn(cid, ctx.ts_on(start + timedelta(days=9)), total * ctx.uniform(0.55, 0.7),
                        "out", "transfer", "Emirates NBD Home Loans", "AE", "Mortgage instalment"))
    txns.append(ctx.txn(cid, ctx.ts_on(start + timedelta(days=11)), total * ctx.uniform(0.08, 0.12),
                        "out", "transfer", "Prime Building Management LLC", "AE",
                        "Service charges"))
    area = ctx.choice(["International City", "Al Nahda", "Deira", "Al Qusais", "JVC"])
    _append_kyc(c, f"Owns a {n}-unit residential building in {area} (title deed on file); "
                   f"tenancy contracts registered on Ejari from {_fmt(start)}; tenants pay "
                   f"monthly rent of AED 3,500 to 7,000 by transfer; mortgage with "
                   f"Emirates NBD Home Loans.")
    return Plant(txns, txns, "close", "funnel", notes="landlord collecting rent")


def lookalike_profile_mismatch(ctx: Ctx, c: Customer, start: date) -> Plant:
    cid, inc = c["customer_id"], c["declared_monthly_income_aed"]
    amt = round(inc * ctx.uniform(4.0, 10.0), -3)
    kind = ctx.choice(["property", "inheritance", "bonus"] if c["segment"] == "salaried"
                      else ["property", "inheritance"])
    if kind == "property":
        area = ctx.choice(["JVC", "Dubai Silicon Oasis", "Al Furjan", "Arjan", "Mirdif"])
        payer, ref = "Dubai Land Department Trustee Account", "Property sale proceeds"
        note = (f"Sold apartment in {area} for AED {amt:,.0f}, {start:%b %Y}; sale agreement "
                f"and DLD transfer on file.")
    elif kind == "inheritance":
        payer, ref = f"Estate of {c['_family'][0]}", "Inheritance"
        note = (f"Inheritance of AED {amt:,.0f} from the estate of {c['_family'][0]} "
                f"expected {start:%b %Y}; court distribution order on file.")
    else:
        payer, ref = c["_employer"], "Annual bonus"
        note = (f"Annual bonus of AED {amt:,.0f} from {c['_employer']} paid {start:%b %Y}; "
                f"employer bonus letter on file.")
    t = ctx.txn(cid, ctx.ts_on(start), amt, "in", "transfer", payer, "AE", ref)
    _append_kyc(c, note)
    return Plant([t], [t], "close", "profile_mismatch", notes=f"{kind} documented in KYC")


def lookalike_dormant_reactivation(ctx: Ctx, c: Customer, start: date) -> Plant:
    c["_quiet"] = True
    cid, inc, name = c["customer_id"], c["declared_monthly_income_aed"], c["full_name"]
    left = start - timedelta(days=ctx.randint(190, 230))
    history = dormant_history(ctx, c, left)
    employer = ctx.company_name()
    country = ctx.choice(["CA", "GB", "AU"])
    savings = inc * ctx.uniform(1.5, 3.0)
    txns = [ctx.txn(cid, ctx.ts_on(start), savings, "in", "transfer", name, country,
                    "Own funds from abroad")]
    pay = start + timedelta(days=ctx.randint(8, 14))
    txns.append(ctx.txn(cid, ctx.ts_on(pay, 5, 9), inc, "in", "transfer", employer, "AE",
                        f"Salary {pay:%b}"))
    spend = [ctx.txn(cid, ctx.ts_on(start + timedelta(days=ctx.randint(1, 20))),
                     ctx.uniform(30, 600), "out", "card", ctx.choice(c["_merchants"]), "AE")
             for _ in range(ctx.randint(6, 12))]
    study = ctx.choice(["studying", "working on contract", "on extended family leave"])
    _append_kyc(c, f"Account inactive from {left:%b %Y} while customer was {study} in "
                   f"{country_name(country)}; returned to the UAE and joined {employer} on "
                   f"{_fmt(start - timedelta(days=3))}. Employment contract on file.")
    return Plant(history + txns + spend, txns, "close", "dormant_reactivation",
                 notes="return from abroad documented in KYC")


def lookalike_high_risk_geo(ctx: Ctx, c: Customer, start: date) -> Plant:
    cid, inc = c["customer_id"], c["declared_monthly_income_aed"]
    country = ctx.choice(ctx.cfg["high_risk_countries"])
    relative = ctx.person_name(country)
    amt = round(max(inc * ctx.uniform(0.1, 0.25), 2000), -2)
    txns, d = [], start
    for _ in range(ctx.randint(2, 3)):
        txns.append(ctx.txn(cid, ctx.ts_on(d), amt * ctx.uniform(0.95, 1.05), "out", "transfer",
                            relative, country, "Medical expenses"))
        d += timedelta(days=ctx.randint(12, 15))
    _append_kyc(c, f"Spouse's family lives in {country_name(country)}. Since {start:%b %Y} "
                   f"customer supports father-in-law {relative} with hospital costs, about "
                   f"AED {amt:,.0f} every two weeks; hospital letter and marriage certificate "
                   f"on file.")
    return Plant(txns, txns, "close", "high_risk_geo", notes="documented family medical support")


LOOKALIKE_PLANTS = {
    "structuring": lookalike_structuring,
    "pass_through": lookalike_pass_through,
    "funnel": lookalike_funnel,
    "profile_mismatch": lookalike_profile_mismatch,
    "dormant_reactivation": lookalike_dormant_reactivation,
    "high_risk_geo": lookalike_high_risk_geo,
}
