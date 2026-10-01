"""Retention (PRD Privacy: datasets deleted after 24 hours).

On startup and every hour:
- dataset folders older than SAABIT_RETENTION_HOURS (default 24) are deleted, except the
  shared sample's folder;
- evidence cards older than that are deleted, including the sample's question cards;
- plan cache entries older than 7 days are deleted.

Never touched: the prepared sample cache (it is the sample itself, rebuilt only at image build)
and anything outside the storage and plan cache folders (such as a committed plan seed).
"""

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.pipeline import CARDS_DIR
from app.core.storage import ID_PATTERN, METADATA_FILE

RETENTION_ENV = "SAABIT_RETENTION_HOURS"
DEFAULT_RETENTION_HOURS = 24.0
PLAN_CACHE_DAYS = 7

logger = logging.getLogger(__name__)


@dataclass
class SweepResult:
    datasets: int = 0
    cards: int = 0
    plans: int = 0


def retention_seconds() -> float:
    try:
        hours = float(os.environ.get(RETENTION_ENV) or DEFAULT_RETENTION_HOURS)
    except ValueError:
        hours = DEFAULT_RETENTION_HOURS
    return max(hours, 0.0) * 3600


def created_at(folder: Path) -> float:
    """When the dataset was uploaded: metadata created_at, else the folder's change time."""
    try:
        metadata = json.loads((folder / METADATA_FILE).read_text(encoding="utf-8"))
        return datetime.fromisoformat(metadata["created_at"]).timestamp()
    except (OSError, ValueError, KeyError, TypeError):
        return folder.stat().st_mtime


def old_files(folder: Path, pattern: str, cutoff: float) -> list[Path]:
    if not folder.is_dir():
        return []
    return [p for p in folder.glob(pattern) if p.is_file() and p.stat().st_mtime < cutoff]


def sweep(storage_root: Path, sample_id: str | None, plan_cache: Path,
          now: float | None = None) -> SweepResult:
    """Delete what is past its retention. Safe to call at any time; errors are logged."""
    now = time.time() if now is None else now
    cutoff = now - retention_seconds()
    result = SweepResult()
    folders = [f for f in storage_root.iterdir()
               if f.is_dir() and ID_PATTERN.fullmatch(f.name)] if storage_root.is_dir() else []
    for folder in folders:
        try:
            if folder.name != sample_id and created_at(folder) < cutoff:
                shutil.rmtree(folder)
                result.datasets += 1
                continue
            for card in old_files(folder / CARDS_DIR, "*.json", cutoff):
                card.unlink()
                result.cards += 1
        except OSError as error:
            logger.warning("retention could not clean %s (%s)", folder.name,
                           type(error).__name__)
    for entry in old_files(plan_cache, "*.json", now - PLAN_CACHE_DAYS * 86400):
        try:
            entry.unlink()
            result.plans += 1
        except OSError as error:
            logger.warning("retention could not delete a plan cache entry (%s)",
                           type(error).__name__)
    if result.datasets or result.cards or result.plans:
        logger.info("retention removed %d dataset(s), %d card(s), %d cached plan(s)",
                    result.datasets, result.cards, result.plans)
    return result
