"""Post-checks on the model's CaseAssessment. Each error is a sentence the model can act on.

The routing rules check evidence again before anything counts; these checks catch invented
IDs and paraphrased quotes early, so the model gets one chance to fix them.
"""

from __future__ import annotations

import re
from collections.abc import Collection

from app.schemas import CaseAssessment, CustomerProfile

TXN_ID = re.compile(r"\bTXN-\d{6}\b")
CHUNK_ID = re.compile(r"\bCHK-[A-Z]+-[A-Z]+-\d{2}\b")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _cited(a: CaseAssessment, pattern: re.Pattern[str]) -> set[str]:
    """IDs in the ID fields and anywhere in the free text."""
    ids: set[str] = set()
    for b in a.benign_explanations:
        listed = b.evidence_txn_ids if pattern is TXN_ID else b.cited_chunk_ids
        ids.update(listed)
        ids.update(pattern.findall(b.explanation))
    if pattern is CHUNK_ID:
        ids.update(a.cited_chunk_ids)
    for t in [a.activity_summary, *a.concerns, *(m.item for m in a.missing_information)]:
        ids.update(pattern.findall(t))
    return ids


def check_assessment(a: CaseAssessment, *, txn_ids: Collection[str],
                     chunk_ids: Collection[str], profile: CustomerProfile,
                     fired: Collection[str]) -> list[str]:
    errors = []
    if bad := sorted(_cited(a, TXN_ID) - set(txn_ids)):
        errors.append(f"Transaction IDs not in the case data: {', '.join(bad)}. "
                      "Cite only IDs from <untrusted_transaction_data>.")
    if bad := sorted(_cited(a, CHUNK_ID) - set(chunk_ids)):
        errors.append(f"Chunk IDs not in the guidance provided: {', '.join(bad)}.")
    notes = _norm(profile.kyc_notes)
    for b in a.benign_explanations:
        if b.kyc_quote and _norm(b.kyc_quote).strip("\"'") not in notes:
            errors.append(f"kyc_quote for {b.typology} is not word for word in kyc_notes: "
                          f"{b.kyc_quote!r}. Quote exactly or set it to null.")
        if b.typology not in fired:
            errors.append(f"Benign explanation names {b.typology}, which did not fire. "
                          f"Explain only these typologies: {', '.join(sorted(fired)) or 'none'}.")
    if not 0 <= a.confidence <= 1:
        errors.append("confidence must be between 0 and 1.")
    return errors
