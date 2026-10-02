"""Disk cache of finished, verified answers, so asking the same question again recomputes nothing.

The key is the dataset, its column mapping, the plan written out canonically, and the
engine and writer versions. Only verified answers are stored: never a mismatch, an error
or a refusal. Entries live inside the dataset's own storage folder, so the 24-hour
retention (and "Delete my data now") removes them with everything else. Each dataset keeps
at most MAX_ENTRIES; an entry is ignored once its evidence card is gone or it is older than
the retention period. The written answer sentence is stored next to it, per card.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.core import retention

ANSWERS_DIR = "answers"
SENTENCES_DIR = "sentences"
MAX_ENTRIES = 200
# Bump when anything that shapes an answer's numbers or evidence changes (compilers, metric
# definitions, caveat rules, explanation text).
ENGINE_VERSION = "1"


def roles_hash(metadata: dict[str, Any]) -> str:
    """The confirmed column mapping, so re-confirming different columns misses the cache."""
    mapping = sorted((r.get("role"), r.get("column")) for r in metadata.get("roles", []))
    return hashlib.sha256(json.dumps(mapping).encode("utf-8")).hexdigest()[:16]


def answer_key(dataset_id: str, mapping: str, plan: dict[str, Any], writer_version: str) -> str:
    """Stable key for one question on one dataset version."""
    canonical = json.dumps({"dataset": dataset_id, "roles": mapping, "plan": plan,
                            "engine": ENGINE_VERSION, "writer": writer_version},
                           sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def answers_dir(dataset_folder: Path) -> Path:
    return dataset_folder / ANSWERS_DIR


def max_age_seconds() -> float:
    return retention.retention_seconds()


def fresh(path: Path) -> bool:
    return path.is_file() and time.time() - path.stat().st_mtime < max_age_seconds()


def read(dataset_folder: Path, key: str, cards_dir: Path) -> dict[str, Any] | None:
    """The cached answer, or None (missing, expired, unreadable, or its card is gone)."""
    path = answers_dir(dataset_folder) / f"{key}.json"
    if not fresh(path):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    card_id = payload.get("card", {}).get("card_id", "")
    if not (cards_dir / f"{card_id}.json").is_file():
        return None
    return payload


def write(dataset_folder: Path, key: str, payload: dict[str, Any]) -> None:
    """Store a verified answer; keep at most MAX_ENTRIES per dataset (oldest dropped)."""
    if not payload.get("verified"):
        return
    folder = answers_dir(dataset_folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{key}.json").write_text(json.dumps(payload, ensure_ascii=False, default=str),
                                        encoding="utf-8")
    entries = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for old in entries[:-MAX_ENTRIES]:
        old.unlink(missing_ok=True)


def clear(dataset_folder: Path) -> None:
    """Forget every cached answer, e.g. after the columns are confirmed again."""
    for folder in (answers_dir(dataset_folder), answers_dir(dataset_folder) / SENTENCES_DIR):
        if folder.is_dir():
            for path in folder.glob("*.json"):
                path.unlink(missing_ok=True)


def read_sentence(dataset_folder: Path, card_id: str) -> dict[str, Any] | None:
    """A checked LLM sentence already written for this card."""
    path = answers_dir(dataset_folder) / SENTENCES_DIR / f"{card_id}.json"
    if not fresh(path):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_sentence(dataset_folder: Path, card_id: str, sentence: dict[str, Any]) -> None:
    folder = answers_dir(dataset_folder) / SENTENCES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{card_id}.json").write_text(json.dumps(sentence, ensure_ascii=False),
                                            encoding="utf-8")
