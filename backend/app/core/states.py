"""Load the canonical Indian state list (data/states.json) as a lookup."""

import json
from functools import cache
from pathlib import Path

STATES_FILE = Path(__file__).resolve().parents[1] / "data" / "states.json"


def fold(value: str) -> str:
    """Matching key for a state spelling: trimmed and casefolded."""
    return value.strip().casefold()


@cache
def state_lookup() -> dict[str, str]:
    """Folded name or variant -> canonical state or union territory name."""
    data = json.loads(STATES_FILE.read_text(encoding="utf-8"))
    return {
        fold(key): entry["name"]
        for entry in data["states"]
        for key in [entry["name"], *entry["variants"]]
    }


def canonical_states() -> list[str]:
    """The 36 canonical names, in file order."""
    data = json.loads(STATES_FILE.read_text(encoding="utf-8"))
    return [entry["name"] for entry in data["states"]]
