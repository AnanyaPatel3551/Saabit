"""Dataset routes: upload, load the sample, read metadata and roles."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, UploadFile

from app.api.errors import LLMPaused, NotCleaned
from app.api.sample import (
    SAMPLE_PATH,
    SAMPLE_ROLES,
    get_sample_cache_dir,
    get_sample_path,
    read_cached_sample,
    shared_sample,
)
from app.api.schemas import (
    CardOut,
    ConfirmIn,
    DataCheckOut,
    DatasetOut,
    OverviewOut,
    PlanOut,
    QuestionIn,
    RoleOut,
    RunOut,
)
from app.api.shared import FIXES_FILE, clean_dataset, describe, source_file, validate_roles
from app.core import detect, ingest, overview, pipeline, storage
from app.core.plan import Plan

__all__ = ["SAMPLE_PATH", "SAMPLE_ROLES", "get_sample_path", "get_storage_root", "router"]

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def get_storage_root() -> Path:
    """Where dataset folders live. Overridden in tests."""
    return storage.storage_root()


StorageRoot = Annotated[Path, Depends(get_storage_root)]
SampleCache = Annotated[Path, Depends(get_sample_cache_dir)]


@router.post("", response_model=DatasetOut)
def upload_dataset(file: UploadFile, root: StorageRoot) -> DatasetOut:
    """Upload a CSV/XLSX; returns the dataset id and suggested roles (not yet confirmed).

    The upload is streamed to disk in chunks and inspected from there; a rejected file
    leaves nothing behind.
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
        storage.write_metadata(root, dataset_id, dataset.model_dump(mode="json"))
    except BaseException:
        storage.delete_dataset(root, dataset_id)
        raise
    return dataset


@router.post("/sample", response_model=DatasetOut)
def load_sample(cache_dir: SampleCache) -> DatasetOut:
    """Return the prepared sample with its roles confirmed and data cleaned (FR-1.4)."""
    return shared_sample(cache_dir)


def cached_sample_if(dataset_id: str, cache_dir: Path) -> DatasetOut | None:
    """The shared sample's metadata when dataset_id is the sample's id, else None."""
    sample = read_cached_sample(cache_dir)
    return sample if sample is not None and sample.dataset_id == dataset_id else None


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


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, root: StorageRoot, cache_dir: SampleCache) -> DatasetOut:
    """Metadata and roles for a stored dataset, including the shared sample."""
    sample = cached_sample_if(dataset_id, cache_dir)
    if sample is not None:
        return sample
    return DatasetOut.model_validate(storage.read_metadata(root, dataset_id))


@router.post("/{dataset_id}/confirm", response_model=DataCheckOut)
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


@router.get("/{dataset_id}/overview", response_model=OverviewOut)
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


@router.post("/{dataset_id}/plan", response_model=PlanOut)
def plan_question(
    dataset_id: str, body: QuestionIn, root: StorageRoot, cache_dir: SampleCache
) -> PlanOut:
    """Turn a typed question into a validated plan (FR-4.1 to FR-4.5).

    The planner and LLM client are imported here, not at startup.
    """
    from app.core import planner

    try:
        result = planner.make_plan(body.question, dataset_id, root, cache_dir)
    except planner.LLMUnavailable as error:
        raise LLMPaused(error.message) from error
    return PlanOut(plan=result.plan, caveats=result.caveats, cached=result.cached)


@router.post("/{dataset_id}/run", response_model=RunOut)
def run_plan(
    dataset_id: str, plan: Plan, root: StorageRoot, cache_dir: SampleCache, question: str = ""
) -> RunOut:
    """Run a plan through both engines, then write a checked answer sentence.

    question (optional query parameter) gives the writer context and lets numbers the user
    typed appear in the sentence. If the LLM is down, a template sentence is used.
    """
    from app.core import narrate  # the writer reaches the LLM, so it is imported here

    card = pipeline.run_plan(dataset_id, plan, root, cache_dir)
    answer = narrate.write_answer(question, Plan.model_validate(card.plan), card.result,
                                  card.verified, card.sql_result, card.pandas_result)
    return RunOut(verified=card.verified, sentence=answer.text, source=answer.source,
                  note=answer.note, card=CardOut.model_validate(card))


@router.get("/{dataset_id}/fixes", response_class=Response)
def get_fixes(dataset_id: str, root: StorageRoot, cache_dir: SampleCache) -> Response:
    """The full fix log as a CSV download (FR-3.4)."""
    if cached_sample_if(dataset_id, cache_dir) is not None:
        path = cache_dir / FIXES_FILE
    else:
        path = storage.dataset_dir(root, dataset_id) / FIXES_FILE
        if not (path.parent / storage.METADATA_FILE).is_file():
            raise storage.DatasetNotFound(dataset_id)
    if not path.is_file():
        raise NotCleaned("The fix log is written when the columns are confirmed. Confirm first.")
    return Response(
        content=path.read_text(encoding="utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="fixes_{dataset_id}.csv"'},
    )
