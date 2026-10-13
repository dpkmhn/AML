"""get_profile: the customer's KYC profile, read through the copilot_ro role."""

from __future__ import annotations

from sqlalchemy import text

from app.db import session
from app.schemas import CustomerProfile

_SQL = text("""
SELECT customer_id, full_name, segment, occupation, declared_monthly_income_aed,
       expected_activity, risk_rating, is_pep, nationality, account_opened, kyc_notes
FROM customers
WHERE customer_id = :customer_id
""")


def get_profile(customer_id: str) -> CustomerProfile:
    with session("ro") as s:
        row = s.execute(_SQL, {"customer_id": customer_id}).mappings().one_or_none()
    if row is None:
        raise LookupError(f"no customer {customer_id}")
    return CustomerProfile.model_validate(dict(row))
