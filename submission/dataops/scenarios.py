"""Scenario picker support: read fixtures/scenarios.json so an operator can
jump straight to a named scenario's sku/warehouse pair in the levers screen.

ponytail: scenarios.json describes *outcomes* (sku, warehouse, target,
expected status), not a fabricator recipe -- there is no existing mapping
from "HEALTHY_STOCK" to the fabricator calls that would produce it, and
inventing one is a Phase-A-sized undertaking on its own. This reads the
catalogue and jumps to the pair; it does not re-fabricate the scenario's
underlying data. Add a recipe field to scenarios.json if one-click
re-fabrication is wanted later.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_scenarios(path: str = "fixtures/scenarios.json") -> list[dict]:
    data = json.loads(Path(path).read_text())
    combined = list(data.get("acceptance_scenarios", [])) + list(data.get("phase_a_scenarios", []))
    return combined
