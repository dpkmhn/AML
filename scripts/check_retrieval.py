"""Retrieval check: for each typology the top filtered result comes from its own document.

    uv run python -m app.rag.ingest
    uv run python scripts/check_retrieval.py

Needs Postgres with guidance_chunks loaded and OPENAI_API_KEY for the query embeddings.
Uses each typology's first planted golden case to build a realistic query.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.retrieve import build_query, retrieve_guidance  # noqa: E402
from app.schemas import TYPOLOGIES  # noqa: E402
from data.build_golden import GOLDEN_PATH  # noqa: E402
from data.local_data import LocalData  # noqa: E402


def main() -> None:
    data = LocalData()
    golden = [json.loads(x) for x in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if x]
    passed = 0
    for ty in TYPOLOGIES:
        case = next(g for g in golden if ty in g["typologies"])
        query = build_query(ty, data.features(case["alert_id"]))
        filtered = retrieve_guidance([ty], query, k=4)
        unfiltered = retrieve_guidance([ty], query, k=4, use_filter=False)
        ok = bool(filtered) and filtered[0].typology == ty
        passed += ok
        print(f"\n{'PASS' if ok else 'FAIL'} {ty}  ({case['alert_id']})\n  query: {query}")
        for label, chunks in (("filtered", filtered), ("unfiltered", unfiltered)):
            print(f"  {label}:")
            for c in chunks:
                print(f"    {c.similarity:.3f} {c.chunk_id:<16} {c.typology:<22} {c.section}")
    print(f"\n{passed}/{len(TYPOLOGIES)} typologies: top filtered result from their own document")
    sys.exit(0 if passed == len(TYPOLOGIES) else 1)


if __name__ == "__main__":
    main()
