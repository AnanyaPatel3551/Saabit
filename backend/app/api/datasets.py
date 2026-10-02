"""Dataset routes: upload, load the sample, read metadata and roles."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response, UploadFile

from app.api.access import KEY_HASH_FIELD, KEY_HEADER, key_matches, new_key
from app.api.errors import Forbidden, LLMPaused, NotCleaned
from app.api.observe import note
from app.api.ratelimit import ANSWERS, QUESTIONS, UPLOADS, limit
from app.api.sample import (
    SAMPLE_PATH,
    SAMPLE_ROLES,
    copy_shopify_sample,
    get_sample_cache_dir,
    get_sample_path,
    read_cached_sample,
    shared_sample,
)
from app.api.schemas import (
    CardOut,
    Comparison,
    ConfirmIn,
    DataCheckOut,
    DatasetOut,
    OverviewOut,
    PlanOut,
    QuestionIn,
    RoleOut,
    RunOut,
    UploadOut,
)
from app.api.shared import FIXES_FILE, clean_dataset, describe, source_file, validate_roles
from app.core import (
    answer_cache,
    coverage,
    detect,
    evidence,
    explain,
    ingest,
    overview,
    pipeline,
    storage,
)
from app.core.plan import Plan

PREVIEW_ROWS = 5  # source rows shown under each answer; the CSV has them all

__all__ = ["SAMPLE_PATH", "SAMPLE_ROLES", "get_sample_path", "get_storage_root", "router"]

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def get_storage_root() -> Path:
    """Where dataset folders live. Overridden in tests."""
    return storage.storage_root()


StorageRoot = Annotated[Path, Depends(get_storage_root)]
SampleCache = Annotated[Path, Depends(get_sample_cache_dir)]
DatasetKey = Annotated[str | None, Header(alias=KEY_HEADER)]


@router.post("", response_model=UploadOut, dependencies=[Depends(limit(UPLOADS))])
def upload_dataset(file: UploadFile, root: StorageRoot) -> UploadOut:
    """Upload a CSV/XLSX; returns the dataset id, suggested roles and its access key.

    The upload is streamed to disk in chunks and inspected from there; a rejected file
    leaves nothing behind. The access key is returned only here; just its hash is stored.
    """
    filename = file.filename or ""
    extension = ingest.extension_of(filename)
    dataset_id, folder = storage.new_dataset(root)
    try:
        raw = storage.raw_path(folder, extension)
        size = ingest.save_upload(file.file, raw)
        table = ingest.read_table(raw, filename, folder)
        detection = detect.detect_roles(table.head, table.rows)
        dataset = describe(
            dataset_id, filename, size, table.rows, table.columns, detection, confirmed=False
        )
        del table
        ingest.release_memory()
        key, key_hash = new_key()
        storage.write_metadata(root, dataset_id,
                               {**dataset.model_dump(mode="json"), KEY_HASH_FIELD: key_hash})
    except BaseException:
        storage.delete_dataset(root, dataset_id)
        raise
    return UploadOut(**dataset.model_dump(), access_key=key)


@router.post("/sample", response_model=DatasetOut)
def load_sample(cache_dir: SampleCache) -> DatasetOut:
    """Return the prepared sample with its roles confirmed and data cleaned (FR-1.4)."""
    return shared_sample(cache_dir)


@router.post("/sample/shopify", response_model=UploadOut,
             dependencies=[Depends(limit(UPLOADS))])
def load_shopify_sample(root: StorageRoot, cache_dir: SampleCache) -> UploadOut:
    """A copy of the synthetic Shopify-style file, with suggested roles to confirm (not real
    data). It goes through the same confirm and cleaning steps as an upload, and gets its
    own access key."""
    return copy_shopify_sample(cache_dir, root)


def cached_sample_if(dataset_id: str, cache_dir: Path) -> DatasetOut | None:
    """The shared sample's metadata when dataset_id is the sample's id, else None."""
    sample = read_cached_sample(cache_dir)
    return sample if sample is not None and sample.dataset_id == dataset_id else None


def check_dataset_key(dataset_id: str, key: str | None, root: Path, cache_dir: Path) -> None:
    """Raise DatasetNotFound (404) unless this is the shared sample or the key matches.

    A wrong key gets the same answer as an unknown id, so it does not reveal that the
    dataset exists. An upload stored without a key hash cannot be opened at all.
    """
    if cached_sample_if(dataset_id, cache_dir) is not None:
        return
    stored = storage.read_metadata(root, dataset_id).get(KEY_HASH_FIELD)
    if not key_matches(key, stored):
        raise storage.DatasetNotFound(dataset_id)


def require_dataset_key(dataset_id: str, root: StorageRoot, cache_dir: SampleCache,
                        key: DatasetKey = None) -> None:
    """Route dependency: the X-Dataset-Key header must unlock this dataset."""
    check_dataset_key(dataset_id, key, root, cache_dir)


KeyChecked = [Depends(require_dataset_key)]


def confirmed_role_list(previous: list[RoleOut], roles: dict[str, str]) -> list[RoleOut]:
    """Every role with the column the user chose; samples are kept when the column is unchanged."""
    before = {r.role: r for r in previous}
    result = []
    for role in detect.ROLES:
        column = roles.get(role)
        old = before.get(role)
        samples = old.samples if old is not None and old.column == column else []
        reasons = ["confirmed by the user"] if column else ["not used"]
        result.append(RoleOut(role=role, column=column, confidence=1.0 if column else 0.0,
                              reasons=reasons, samples=samples))
    return result


@router.get("/{dataset_id}", response_model=DatasetOut, dependencies=KeyChecked)
def get_dataset(dataset_id: str, root: StorageRoot, cache_dir: SampleCache) -> DatasetOut:
    """Metadata and roles for a stored dataset, including the shared sample."""
    sample = cached_sample_if(dataset_id, cache_dir)
    if sample is not None:
        return sample
    return DatasetOut.model_validate(storage.read_metadata(root, dataset_id))


@router.delete("/{dataset_id}", dependencies=KeyChecked)
def delete_dataset(dataset_id: str, root: StorageRoot, cache_dir: SampleCache) -> dict[str, str]:
    """Delete an uploaded dataset now: its raw file, cleaned data and evidence cards.

    The shared sample is used by everyone, so it cannot be deleted.
    """
    if cached_sample_if(dataset_id, cache_dir) is not None:
        raise Forbidden("The shared sample cannot be deleted; only your own uploads can.")
    storage.read_metadata(root, dataset_id)  # 404 when there is no such dataset
    storage.delete_dataset(root, dataset_id)
    return {"deleted": dataset_id}


@router.post("/{dataset_id}/confirm", response_model=DataCheckOut,
             dependencies=KeyChecked)
def confirm_roles(
    dataset_id: str, body: ConfirmIn, root: StorageRoot, cache_dir: SampleCache,
    background: BackgroundTasks,
) -> DataCheckOut:
    """Accept the final roles, clean the data and return the data check (FR-2.4, Step 3).

    Insights and recommendations are then computed in the background; GET /overview shows
    "computing" until they are ready. The sample's roles are fixed and it is cleaned at
    image build, so confirming it simply returns its stored data check.
    """
    sample = cached_sample_if(dataset_id, cache_dir)
    if sample is not None and sample.data_check is not None:
        return sample.data_check
    dataset = DatasetOut.model_validate(storage.read_metadata(root, dataset_id))
    roles = validate_roles(body.roles, dataset.columns)
    folder = storage.dataset_dir(root, dataset_id)
    check = clean_dataset(dataset_id, source_file(folder), roles, folder)
    answer_cache.clear(folder)  # answers from an earlier confirm no longer apply
    dataset.roles = confirmed_role_list(dataset.roles, roles)
    dataset.roles_confirmed = True
    dataset.missing_required = []
    dataset.unmapped_columns = [c for c in dataset.columns if c not in set(roles.values())]
    dataset.data_check = check
    storage.write_metadata(root, dataset_id, dataset.model_dump(mode="json"))
    overview_path = folder / overview.OVERVIEW_FILE
    overview.mark_computing(overview_path)
    workspace = pipeline.Workspace(dataset_id, root, cache_dir, folder / pipeline.CARDS_DIR)
    background.add_task(overview.compute_overview, workspace, check.model_dump(mode="json"),
                        overview_path)
    return check


@router.get("/{dataset_id}/overview", response_model=OverviewOut, dependencies=KeyChecked)
def get_overview(dataset_id: str, root: StorageRoot, cache_dir: SampleCache) -> OverviewOut:
    """Data check, insight cards and recommendations ("computing" until they are ready)."""
    sample = cached_sample_if(dataset_id, cache_dir)
    if sample is not None:
        dataset, folder = sample, cache_dir
    else:
        dataset = DatasetOut.model_validate(storage.read_metadata(root, dataset_id))
        folder = storage.dataset_dir(root, dataset_id)
    if dataset.data_check is None:
        raise NotCleaned("Insights are computed after the columns are confirmed. Confirm first.")
    saved = overview.read_overview(folder / overview.OVERVIEW_FILE) or {"status": "computing"}
    return OverviewOut(
        status=saved["status"],
        reason=saved.get("reason"),
        computed_at=saved.get("computed_at"),
        months=saved.get("months"),
        data_check=dataset.data_check,
        insights=saved.get("insights", []),
        recommendations=saved.get("recommendations", []),
        rules=saved.get("rules", []),
    )


@router.post("/{dataset_id}/plan", response_model=PlanOut,
             dependencies=[Depends(limit(QUESTIONS)), *KeyChecked])
def plan_question(
    dataset_id: str, body: QuestionIn, root: StorageRoot, cache_dir: SampleCache,
    request: Request,
) -> PlanOut:
    """Turn a typed question into a validated plan (FR-4.1 to FR-4.5).

    The planner and LLM client are imported here, not at startup.
    """
    from app.core import planner
    from app.llm.config import served_by

    served_by.set(None)
    try:
        result = planner.make_plan(body.question, dataset_id, root, cache_dir)
    except planner.LLMUnavailable as error:
        note(request, llm_provider="none")
        raise LLMPaused(error.message) from error
    note(request, plan_status=result.plan.status,
         llm_provider="plan cache" if result.cached else served_by.get())
    return PlanOut(plan=result.plan, caveats=result.caveats, cached=result.cached)


@router.post("/{dataset_id}/run", response_model=RunOut,
             dependencies=[Depends(limit(ANSWERS)), *KeyChecked])
def run_plan(
    dataset_id: str, plan: Plan, root: StorageRoot, cache_dir: SampleCache, request: Request,
) -> RunOut:
    """Run a plan through both engines and return the numbers at once (numbers first).

    No LLM call here: the sentence is the template, and POST /api/cards/{id}/sentence writes
    the LLM sentence afterwards. Questions are never sent in this URL. A verified answer to
    the same plan on the same columns is served from the answer cache with nothing recomputed.
    """
    from app.core import narrate
    from app.llm.prompts import WRITER_VERSION

    context = pipeline.load_context(dataset_id, root, cache_dir)
    answers_home = context.cards_dir.parent  # the dataset's storage folder (retention deletes it)
    key = answer_cache.answer_key(dataset_id, answer_cache.roles_hash(dataset_metadata(
        dataset_id, root, cache_dir)), plan.model_dump(mode="json"), WRITER_VERSION)
    hit = answer_cache.read(answers_home, key, context.cards_dir)
    if hit is not None:
        saved = answer_cache.read_sentence(answers_home, hit["card"]["card_id"])
        if saved is not None:  # the sentence already shown for this answer, word for word
            hit = {**hit, "sentence": saved["sentence"], "source": saved["source"],
                   "sentence_status": "final"}
        note(request, plan_status=plan.status, verified=True, source=hit.get("source"),
             cached=True)
        return RunOut.model_validate({**hit, "cached": True})

    card = pipeline.run_plan(dataset_id, plan, root, cache_dir)
    info = pipeline.dataset_info(context)
    partial = coverage.partial_coverage(info.date_min, info.date_max)
    answer = narrate.instant_answer(Plan.model_validate(card.plan), card.result, card.verified,
                                    card.sql_result, card.pandas_result, partial)
    note(request, plan_status=plan.status, verified=card.verified, source=answer.source)
    out = RunOut(verified=card.verified, sentence=answer.text, source=answer.source,
                 sentence_status="pending" if card.verified else "final",
                 note=answer.note, card=CardOut.model_validate(card),
                 comparison=comparison_for(card, dataset_id, root, cache_dir),
                 explanation=explain.explanation(card, context.folder / FIXES_FILE,
                                                 info.date_min, info.date_max),
                 rows_preview=preview_rows(context.query_db, card))
    if card.verified:
        answer_cache.write(answers_home, key, out.model_dump(mode="json"))
    return out


def dataset_metadata(dataset_id: str, root: Path, cache_dir: Path) -> dict:
    """The stored metadata of an upload, or of the shared sample from its cache."""
    sample = cached_sample_if(dataset_id, cache_dir)
    if sample is not None:
        return sample.model_dump(mode="json")
    return storage.read_metadata(root, dataset_id)


def preview_rows(query_db: Path, card: evidence.EvidenceCard) -> list[dict]:
    """The first few source rows behind a card (none when the card has no rows)."""
    if not card.row_count:
        return []
    return evidence.source_rows(query_db, card, 1)["rows"][:PREVIEW_ROWS]


def comparison_for(card: evidence.EvidenceCard, dataset_id: str, root: Path,
                   cache_dir: Path) -> Comparison | None:
    """For a filtered single number, the same measure over all orders in the same period.

    It runs through both engines like any answer and is left out unless they agree.
    """
    plan = Plan.model_validate(card.plan)
    if not card.verified or plan.group_by or not plan.filters:
        return None
    overall = pipeline.run_plan(dataset_id, plan.model_copy(update={"filters": []}), root,
                                cache_dir)
    if not overall.verified or not overall.result:
        return None
    return Comparison(label="all orders", value=overall.result[0].get("value"), verified=True,
                      card_id=overall.card_id)


@router.get("/{dataset_id}/fixes", response_class=Response, dependencies=KeyChecked)
def get_fixes(dataset_id: str, root: StorageRoot, cache_dir: SampleCache) -> Response:
    """The full fix log as a CSV download (FR-3.4)."""
    if cached_sample_if(dataset_id, cache_dir) is not None:
        path = cache_dir / FIXES_FILE
    else:
        path = storage.dataset_dir(root, dataset_id) / FIXES_FILE
        if not (path.parent / storage.METADATA_FILE).is_file():
            raise storage.DatasetNotFound(dataset_id)
    if not path.is_file():
        raise NotCleaned("The clean-up list is ready once your columns are confirmed. "
                         "Confirm them first.")
    return Response(
        content=path.read_text(encoding="utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="fixes_{dataset_id}.csv"'},
    )
