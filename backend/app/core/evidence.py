"""Evidence cards: the saved record behind every answer (FR-8.1)."""

import json
import re
import secrets
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.core import compile_sql
from app.core.plan import Plan

CARD_ID_PATTERN = re.compile(r"^([0-9a-f]{12})-([0-9a-f]{8})$")
PAGE_SIZE = 100


class CardNotFound(Exception):
    code = "card_not_found"

    def __init__(self, card_id: str) -> None:
        self.message = f"No evidence card with id '{card_id}'."
        super().__init__(self.message)


@dataclass
class EvidenceCard:
    """Everything needed to check an answer: plan, both engines' code, result, caveats."""

    card_id: str
    dataset_id: str
    plan: dict
    sql: str
    pandas_code: str
    verified: bool
    result: list[dict]
    caveats: list[str]
    row_count: int  # cleaned lines matching the plan's dates and filters
    sql_result: list[dict] | None = None  # both results are kept when the engines disagree
    pandas_result: list[dict] | None = None
    mismatches: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def new_card_id(dataset_id: str) -> str:
    """'<dataset id>-<8 random hex>', so the card's dataset can be found from its id."""
    return f"{dataset_id}-{secrets.token_hex(4)}"


def dataset_of(card_id: str) -> str:
    match = CARD_ID_PATTERN.fullmatch(card_id)
    if match is None:
        raise CardNotFound(card_id)
    return match.group(1)


def card_path(cards_dir: Path, card_id: str) -> Path:
    dataset_of(card_id)
    return cards_dir / f"{card_id}.json"


def save_card(cards_dir: Path, card: EvidenceCard) -> Path:
    cards_dir.mkdir(parents=True, exist_ok=True)
    path = card_path(cards_dir, card.card_id)
    path.write_text(json.dumps(asdict(card), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_card(cards_dir: Path, card_id: str) -> EvidenceCard:
    path = card_path(cards_dir, card_id)
    if not path.is_file():
        raise CardNotFound(card_id)
    return EvidenceCard(**json.loads(path.read_text(encoding="utf-8")))


def page_count(total: int, page_size: int = PAGE_SIZE) -> int:
    return max(1, -(-total // page_size))


def source_rows(query_db: Path, card: EvidenceCard, page: int) -> dict:
    """One page of the cleaned lines behind a card, as JSON-ready rows."""
    plan = Plan.model_validate(card.plan)
    frame = compile_sql.source_rows_page(query_db, plan, page, PAGE_SIZE)
    rows = json.loads(frame.to_json(orient="records", date_format="iso"))
    return {
        "card_id": card.card_id,
        "page": page,
        "page_size": PAGE_SIZE,
        "total_rows": card.row_count,
        "pages": page_count(card.row_count),
        "rows": rows,
    }


def source_rows_csv(query_db: Path, card: EvidenceCard) -> Iterator[bytes]:
    """Every cleaned line behind a card, streamed as CSV."""
    return compile_sql.source_rows_csv(query_db, Plan.model_validate(card.plan))
