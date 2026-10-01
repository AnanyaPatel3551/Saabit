"""Card routes: the source rows behind an evidence card."""

from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.datasets import SampleCache, StorageRoot
from app.api.schemas import CardOut, RowsOut
from app.core import evidence, pipeline

router = APIRouter(prefix="/api/cards", tags=["cards"])


@router.get("/{card_id}", response_model=CardOut)
def get_card(card_id: str, root: StorageRoot, cache_dir: SampleCache) -> CardOut:
    """A saved evidence card: plan, SQL, pandas code, result and caveats (FR-8.1)."""
    context = pipeline.load_context(evidence.dataset_of(card_id), root, cache_dir)
    return CardOut.model_validate(
        evidence.load_card(pipeline.card_dirs(context, cache_dir), card_id))


@router.get("/{card_id}/rows", response_model=None)
def card_rows(
    card_id: str,
    root: StorageRoot,
    cache_dir: SampleCache,
    page: int = Query(default=1, ge=1),
    output: Literal["json", "csv"] = Query(default="json", alias="format"),
) -> RowsOut | StreamingResponse:
    """The cleaned lines behind a card: one page as JSON, or all of them as a CSV download."""
    context = pipeline.load_context(evidence.dataset_of(card_id), root, cache_dir)
    card = evidence.load_card(pipeline.card_dirs(context, cache_dir), card_id)
    if output == "csv":
        return StreamingResponse(
            evidence.source_rows_csv(context.query_db, card),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="rows_{card_id}.csv"'},
        )
    return RowsOut(**evidence.source_rows(context.query_db, card, page))
