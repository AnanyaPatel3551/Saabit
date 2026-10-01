"""The overview: data check, insight cards and recommendations, cached as overview.json."""

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core import insights, pipeline, recommend

OVERVIEW_FILE = "overview.json"
logger = logging.getLogger(__name__)


def now() -> str:
    return datetime.now(UTC).isoformat()


def write(path: Path, payload: dict[str, Any]) -> None:
    """Write atomically, so a reader never sees half a file."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_overview(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def mark_computing(path: Path) -> None:
    write(path, {"status": "computing", "started_at": now()})


def compute_overview(ws: pipeline.Workspace, data_check: dict[str, Any], path: Path) -> dict:
    """Build insights and recommendations and save them; a failure is saved, never raised."""
    mark_computing(path)
    try:
        info = pipeline.dataset_info(ws.context())
        split = recommend.split_months(info.date_min, info.date_max,
                                       data_check.get("partial_months", []))
        days = (info.date_max - info.date_min).days + 1
        recommendations, rules = recommend.build_recommendations(ws, split, days)
        payload = {
            "status": "ready",
            "computed_at": now(),
            "months": {"training": split.training, "test": split.test},
            "insights": insights.build_insights(ws, data_check),
            "recommendations": recommendations,
            "rules": rules,
        }
    except Exception as error:  # a background job must record its failure, not vanish
        logger.exception("overview failed for %s", ws.dataset_id)
        payload = {"status": "failed", "computed_at": now(),
                   "reason": f"Insights could not be computed ({type(error).__name__})."}
    write(path, payload)
    return payload
