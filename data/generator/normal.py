"""Normal behaviour per segment, plus unplanted noise traits near monitoring thresholds."""

from __future__ import annotations

from datetime import date, timedelta

from data.generator.common import Ctx, Txn, clamp_day, month_starts
from data.generator.customers import Customer

NOISE_TRAITS = ["bonus", "savings_move", "cash_peak", "group_collection", "geo_oneoff", "gift"]
NOISE_WEIGHTS = {"bonus": 2, "savings_move": 2, "cash_peak": 6, "group_collection": 3,
                 "geo_oneoff": 1, "gift": 1}


def generate_normal(ctx: Ctx, customers: list[Customer]) -> list[Txn]:
    txns: list[Txn] = []
    gen = {"salaried": _salaried, "business": _business, "student": _student,
           "retiree": _retiree}
    for c in customers:
        if c["_quiet"]:
            continue
        for m in month_starts(ctx.start, ctx.end):
            txns += gen[c["segment"]](ctx, c, m)
        if c["_noise"]:
            txns += NOISE[c["_noise"]](ctx, c)
    return txns


def assign_noise(ctx: Ctx, customers: list[Customer], exclude: set[str]) -> None:
    """Give about `noise_share` of non-scenario customers one near-threshold trait."""
    pool = [c for c in customers if c["customer_id"] not in exclude and not c["_quiet"]]
    k = round(len(pool) * ctx.cfg["noise_share"])
    for i in ctx.rng.choice(len(pool), k, replace=False):
        c = pool[int(i)]
        options = [t for t in NOISE_TRAITS if _fits(c, t)]
        weights = [NOISE_WEIGHTS[t] for t in options]
        c["_noise"] = ctx.choice(options, p=[w / sum(weights) for w in weights])


def _fits(c: Customer, trait: str) -> bool:
    seg = c["segment"]
    return {
        "bonus": seg == "salaried",
        "savings_move": seg in ("salaried", "retiree"),
        "cash_peak": seg == "business" and c.get("_cash_intensive", False),
        "group_collection": seg in ("salaried", "student") and not c.get("_pays_rent", False),
        "geo_oneoff": seg in ("salaried", "business", "retiree"),
        "gift": seg in ("salaried", "retiree", "student"),
    }[trait]


# ---- shared pieces ------------------------------------------------------------
def _in_range(ctx: Ctx, d: date) -> bool:
    return ctx.start <= d <= ctx.end


def _card_spend(ctx: Ctx, c: Customer, m: date, n: int, median: float) -> list[Txn]:
    out = []
    cap = max(c["declared_monthly_income_aed"] * 0.3, 300)
    for _ in range(n):
        d = clamp_day(m, ctx.randint(1, 31))
        if not _in_range(ctx, d):
            continue
        amt = min(ctx.lognormal_around(median, 0.8), cap)
        out.append(ctx.txn(c["customer_id"], ctx.ts_on(d), max(amt, 8), "out", "card",
                           ctx.choice(c["_merchants"]), "AE"))
    return out


def _atm(ctx: Ctx, c: Customer, m: date, n: int, lo: int, hi: int) -> list[Txn]:
    out = []
    for _ in range(n):
        d = clamp_day(m, ctx.randint(1, 31))
        if _in_range(ctx, d):
            amt = round(ctx.uniform(lo, hi) / 100) * 100
            out.append(ctx.txn(c["customer_id"], ctx.ts_on(d), amt, "out", "cash",
                               reference="ATM withdrawal"))
    return out


def _mon(m: date) -> str:
    return m.strftime("%b")


# ---- segments -----------------------------------------------------------------
def _salaried(ctx: Ctx, c: Customer, m: date) -> list[Txn]:
    cid, inc = c["customer_id"], c["declared_monthly_income_aed"]
    out: list[Txn] = []
    d = clamp_day(m, c["_salary_day"])
    if _in_range(ctx, d):
        out.append(ctx.txn(cid, ctx.ts_on(d, 5, 9), inc * ctx.uniform(0.97, 1.03), "in",
                           "transfer", c["_employer"], "AE", f"Salary {_mon(m)}"))
    if c["_pays_rent"]:
        c.setdefault("_rent", round(inc * ctx.uniform(0.25, 0.35) / 100) * 100)
        d = clamp_day(m, c["_rent_day"])
        if _in_range(ctx, d):
            out.append(ctx.txn(cid, ctx.ts_on(d), c["_rent"], "out", "transfer",
                               c["_landlord"], "AE", f"Rent {_mon(m)}"))
    lo, hi = ctx.cfg["volume"]["salaried_card"]
    out += _card_spend(ctx, c, m, ctx.randint(lo, hi), inc * 0.025)
    out += _atm(ctx, c, m, ctx.randint(0, 2), 200, 2000)
    if c["_remits"] and ctx.chance(0.5):
        d = clamp_day(m, ctx.randint(1, 28))
        name, country = c["_family"]
        if _in_range(ctx, d):
            out.append(ctx.txn(cid, ctx.ts_on(d), inc * ctx.uniform(0.05, 0.15), "out",
                               "transfer", name, country, "Family support"))
    if ctx.chance(0.15):
        d = clamp_day(m, ctx.randint(1, 28))
        if _in_range(ctx, d):
            friend = ctx.person_name(c["nationality"])
            out.append(ctx.txn(cid, ctx.ts_on(d), ctx.uniform(100, 1500), "in", "transfer",
                               friend, "AE", ctx.choice(["Dinner split", "Thanks", "Repay"])))
    return out


def _business(ctx: Ctx, c: Customer, m: date) -> list[Txn]:
    cid, inc = c["customer_id"], c["declared_monthly_income_aed"]
    out: list[Txn] = []
    revenue = inc * ctx.lognormal_around(1.15, 0.2)
    cash_share = ctx.uniform(0.3, 0.6) if c["_cash_intensive"] else ctx.uniform(0.0, 0.1)
    # Client transfers: count from config, amounts rescaled to this month's revenue.
    lo, hi = ctx.cfg["volume"]["business_clients"]
    n = ctx.randint(lo, hi)
    raw = [ctx.lognormal_around(1.0, 0.5) for _ in range(n)]
    scale = revenue * (1 - cash_share) / sum(raw)
    for r in raw:
        d = clamp_day(m, ctx.randint(1, 31))
        if _in_range(ctx, d):
            out.append(ctx.txn(cid, ctx.ts_on(d), r * scale, "in", "transfer",
                               ctx.choice(c["_clients"]), "AE",
                               ctx.choice(["Invoice", "Payment", f"INV-{ctx.randint(1000, 9999)}",
                                           "Order", None])))
    # Cash takings, deposited once or twice a week.
    if cash_share > 0.05:
        k = ctx.randint(4, 8)
        for _ in range(k):
            d = clamp_day(m, ctx.randint(1, 31))
            if _in_range(ctx, d):
                amt = revenue * cash_share / k * ctx.uniform(0.7, 1.3)
                out.append(ctx.txn(cid, ctx.ts_on(d, 9, 20), amt, "in", "cash",
                                   reference=ctx.choice(["Shop takings", "Cash sales", None])))
    # Each supplier is paid on its own fixed day; payroll and rent are monthly.
    spend = revenue * ctx.uniform(0.55, 0.75)
    for s, day in zip(c["_suppliers"], c["_supplier_days"], strict=True):
        d = clamp_day(m, day)
        if _in_range(ctx, d):
            out.append(ctx.txn(cid, ctx.ts_on(d), spend / len(c["_suppliers"])
                               * ctx.uniform(0.7, 1.3), "out", "transfer", s, "AE",
                               f"Supplier payment {_mon(m)}"))
    d = clamp_day(m, 28)
    if _in_range(ctx, d):
        out.append(ctx.txn(cid, ctx.ts_on(d), revenue * ctx.uniform(0.1, 0.18), "out",
                           "transfer", f"{c['_company']} WPS Payroll", "AE",
                           f"Payroll {_mon(m)}"))
    d = clamp_day(m, c["_rent_day"])
    if _in_range(ctx, d):
        c.setdefault("_rent", round(inc * ctx.uniform(0.08, 0.15) / 100) * 100)
        out.append(ctx.txn(cid, ctx.ts_on(d), c["_rent"], "out", "transfer", c["_landlord"],
                           "AE", f"Shop rent {_mon(m)}"))
    lo, hi = ctx.cfg["volume"]["business_card"]
    out += _card_spend(ctx, c, m, ctx.randint(lo, hi), inc * 0.01)
    out += _atm(ctx, c, m, ctx.randint(0, 2), 500, 3000)
    return out


def _student(ctx: Ctx, c: Customer, m: date) -> list[Txn]:
    cid, inc = c["customer_id"], c["declared_monthly_income_aed"]
    out: list[Txn] = []
    d = clamp_day(m, c["_family_day"])
    name, country = c["_family"]
    if _in_range(ctx, d):
        out.append(ctx.txn(cid, ctx.ts_on(d), inc * ctx.uniform(0.95, 1.05), "in", "transfer",
                           name, country, ctx.choice(["Monthly allowance", "For expenses",
                                                      "Allowance"])))
    lo, hi = ctx.cfg["volume"]["student_card"]
    out += _card_spend(ctx, c, m, ctx.randint(lo, hi), inc * 0.05)
    out += _atm(ctx, c, m, ctx.randint(0, 1), 100, 500)
    return out


def _retiree(ctx: Ctx, c: Customer, m: date) -> list[Txn]:
    cid, inc = c["customer_id"], c["declared_monthly_income_aed"]
    out: list[Txn] = []
    d = clamp_day(m, c["_pension_day"])
    if _in_range(ctx, d):
        out.append(ctx.txn(cid, ctx.ts_on(d, 5, 9), inc, "in", "transfer", c["_pension_payer"],
                           c["_pension_country"], f"Pension {_mon(m)}"))
    lo, hi = ctx.cfg["volume"]["retiree_card"]
    out += _card_spend(ctx, c, m, ctx.randint(lo, hi), inc * 0.03)
    out += _atm(ctx, c, m, ctx.randint(1, 3), 200, 1500)
    if ctx.chance(1 / 6):
        d = clamp_day(m, ctx.randint(1, 28))
        name, country = c["_family"]
        if _in_range(ctx, d):
            out.append(ctx.txn(cid, ctx.ts_on(d), inc * ctx.uniform(1.0, 3.0), "out",
                               "transfer", name, country,
                               ctx.choice(["Gift", "Wedding expenses", "Medical bills"])))
    return out


# ---- noise traits: unplanted, unlabelled, near a monitoring threshold ----------------
def _noise_day(ctx: Ctx) -> date:
    return ctx.day_between(ctx.start + timedelta(days=35), ctx.end - timedelta(days=10))


def _bonus(ctx: Ctx, c: Customer) -> list[Txn]:
    d = _noise_day(ctx)
    amt = c["declared_monthly_income_aed"] * ctx.uniform(1.2, 2.0)
    return [ctx.txn(c["customer_id"], ctx.ts_on(d, 5, 9), amt, "in", "transfer",
                    c["_employer"], "AE", "Bonus")]


def _savings_move(ctx: Ctx, c: Customer) -> list[Txn]:
    cid, name = c["customer_id"], c["full_name"]
    d, out = _noise_day(ctx), []
    for _ in range(2):
        amt = ctx.uniform(26000, 60000)
        t_in = ctx.ts_on(d)
        out.append(ctx.txn(cid, t_in, amt, "in", "transfer", name, "AE", "Own transfer"))
        out.append(ctx.txn(cid, t_in + timedelta(hours=ctx.uniform(2, 40)),
                           amt * ctx.uniform(0.85, 0.98), "out", "transfer",
                           f"{name} - Investment account", "AE", "Savings"))
        d += timedelta(days=ctx.randint(5, 14))
    return out


def _cash_peak(ctx: Ctx, c: Customer) -> list[Txn]:
    d, out = _noise_day(ctx), []
    for _ in range(ctx.randint(3, 4)):
        out.append(ctx.txn(c["customer_id"], ctx.ts_on(d, 9, 20), ctx.uniform(43000, 49500),
                           "in", "cash", reference="Shop takings"))
        d += timedelta(days=ctx.randint(1, 4))
    return out


def _group_collection(ctx: Ctx, c: Customer) -> list[Txn]:
    cid, d, out = c["customer_id"], _noise_day(ctx), []
    total = 0.0
    for _ in range(ctx.randint(9, 12)):
        amt = ctx.uniform(300, 2000)
        total += amt
        out.append(ctx.txn(cid, ctx.ts_on(d + timedelta(days=ctx.randint(0, 6))), amt, "in",
                           "transfer", ctx.person_name(c["nationality"]), "AE",
                           ctx.choice(["Trip share", "Georgia trip", "Group trip"])))
    out.append(ctx.txn(cid, ctx.ts_on(d + timedelta(days=8)), total * ctx.uniform(0.9, 1.0),
                       "out", "transfer", "Musafir Travel LLC", "AE", "Group booking"))
    return out


def _geo_oneoff(ctx: Ctx, c: Customer) -> list[Txn]:
    country = ctx.choice(ctx.cfg["high_risk_countries"])
    return [ctx.txn(c["customer_id"], ctx.ts_on(_noise_day(ctx)), ctx.uniform(2000, 8000),
                    "out", "transfer", ctx.person_name(country), country,
                    ctx.choice(["Gift", "Help", "Loan repayment"]))]


def _gift(ctx: Ctx, c: Customer) -> list[Txn]:
    name, country = c["_family"]
    amt = c["declared_monthly_income_aed"] * ctx.uniform(2.2, 3.5)
    return [ctx.txn(c["customer_id"], ctx.ts_on(_noise_day(ctx)), amt, "in", "transfer",
                    name, country, "Gift")]


NOISE = {"bonus": _bonus, "savings_move": _savings_move, "cash_peak": _cash_peak,
         "group_collection": _group_collection, "geo_oneoff": _geo_oneoff, "gift": _gift}
