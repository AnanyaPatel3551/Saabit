"""Card routes: a saved evidence card, its answer sentence, and the source rows behind it."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.datasets import DatasetKey, SampleCache, StorageRoot, check_dataset_key
from app.api.observe import note
from app.api.ratelimit import SENTENCES, limit
from app.api.schemas import CardOut, RowsOut, SentenceIn, SentenceOut
from app.core import answer_cache, evidence, pipeline, storage
from app.core.plan import Plan

router = APIRouter(prefix="/api/cards", tags=["cards"])


def require_card_key(card_id: str, root: StorageRoot, cache_dir: SampleCache,
                     key: DatasetKey = None) -> None:
    """Route dependency: a card opens only with its dataset's key (the sample needs none).

    A wrong key gets the same 404 as a card that does not exist.
    """
    try:
        check_dataset_key(evidence.dataset_of(card_id), key, root, cache_dir)
    except storage.DatasetNotFound as error:
        raise evidence.CardNotFound(card_id) from error


KeyChecked = [Depends(require_card_key)]


@router.get("/{card_id}", response_model=CardOut, dependencies=KeyChecked)
def get_card(card_id: str, root: StorageRoot, cache_dir: SampleCache) -> CardOut:
    """A saved evidence card: plan, SQL, pandas code, result and caveats (FR-8.1)."""
    context = pipeline.load_context(evidence.dataset_of(card_id), root, cache_dir)
    return CardOut.model_validate(
        evidence.load_card(pipeline.card_dirs(context, cache_dir), card_id))


@router.post("/{card_id}/sentence", response_model=SentenceOut,
             dependencies=[Depends(limit(SENTENCES)), *KeyChecked])
def write_sentence(
    card_id: str, body: SentenceIn, root: StorageRoot, cache_dir: SampleCache, request: Request
) -> SentenceOut:
    """The answer sentence for a card, written after the numbers were shown (FR-7).

    The LLM's sentence is used only if every number in it passes the number checker; if the
    LLM is unavailable or its numbers do not check out, the template sentence comes back.
    Unverified cards get no sentence and no LLM call.
    """
    from app.core import narrate  # the writer reaches the LLM, so it is imported here
    from app.llm.config import served_by

    context = pipeline.load_context(evidence.dataset_of(card_id), root, cache_dir)
    card = evidence.load_card(pipeline.card_dirs(context, cache_dir), card_id)
    answers_home = context.cards_dir.parent
    saved = answer_cache.read_sentence(answers_home, card_id)
    if saved is not None:  # the same cached answer asked again: no new AI call
        note(request, verified=card.verified, source=saved.get("source"), cached=True)
        return SentenceOut(**saved)
    served_by.set(None)
    answer = narrate.write_answer(body.question, Plan.model_validate(card.plan), card.result,
                                  card.verified, card.sql_result, card.pandas_result,
                                  partial=pipeline.partial_months_of(context))
    note(request, verified=card.verified, source=answer.source,
         llm_provider=served_by.get() if answer.source == "llm" else None)
    out = SentenceOut(sentence=answer.text, source=answer.source, note=answer.note)
    if answer.source == "llm":
        answer_cache.write_sentence(answers_home, card_id, out.model_dump())
    return out


@router.get("/{card_id}/rows", response_model=None, dependencies=KeyChecked)
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
