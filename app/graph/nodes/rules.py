"""Nodes that run the deterministic rules from stage 2.1 on the case's data."""

from __future__ import annotations

import pandas as pd

from app.audit import audited
from app.graph.state import CaseState
from app.rules import features, typologies
from app.rules.monitoring import load_thresholds


@audited("compute_features")
def compute_features(state: CaseState) -> CaseState:
    a = state["alert"]
    txns = pd.DataFrame([t.model_dump() for t in state["txns"]])
    f = features.compute_features(state["profile"].model_dump(), txns, a.window_start,
                                  a.window_end, load_thresholds())
    return {"features": f}


@audited("detect_typologies")
def detect_typologies(state: CaseState) -> CaseState:
    return {"findings": typologies.detect_typologies(state["features"], load_thresholds())}
