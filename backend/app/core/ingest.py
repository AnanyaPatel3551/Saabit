"""Read CSV/XLSX files from disk in bounded memory; count rows with DuckDB."""

import codecs
import gzip
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, BinaryIO

import duckdb
import openpyxl
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
from openpyxl.utils.exceptions import InvalidFileException

MAX_BYTES = 25 * 1024 * 1024
MAX_ROWS = 500_000
HEAD_ROWS = 50_000
CHUNK_BYTES = 1024 * 1024
SNIFF_BYTES = 64 * 1024
ALLOWED_EXTENSIONS = (".csv", ".xlsx")
GZIP_SUFFIX = ".gz"
UTF8_COPY = "utf8.csv"
XLSX_SIGNATURE = b"PK\x03\x04"
BINARY_SIGNATURES = (
    b"%PDF", XLSX_SIGNATURE, b"\xd0\xcf\x11\xe0", b"\x89PNG", b"\xff\xd8\xff", b"GIF8",
)
DELIMITERS = (",", ";", "\t", "|")
TEXT_DTYPE = pd.StringDtype("pyarrow")
DUCKDB_CONFIG = {"memory_limit": "128MB", "threads": 1}


class UploadError(Exception):
    """A file the user can fix; the API returns it as a 400 with this message."""

    code = "upload_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class UnsupportedFileType(UploadError):
    code = "unsupported_file_type"


class FileTooLarge(UploadError):
    code = "file_too_large"


class TooManyRows(UploadError):
    code = "too_many_rows"


class EmptyFile(UploadError):
    code = "empty_file"


class UnreadableFile(UploadError):
    code = "unreadable_file"


@dataclass(frozen=True)
class Table:
    """What is known about a file without loading all of it.

    rows and columns describe the whole file; head holds at most HEAD_ROWS rows as text.
    """

    rows: int
    columns: list[str]
    head: pd.DataFrame
    encoding: str


def too_large() -> FileTooLarge:
    return FileTooLarge(
        "The file is over 25 MB, which is the upload limit. Try exporting a shorter date range."
    )


def extension_of(filename: str) -> str:
    """Lower-case extension if it is .csv or .xlsx; otherwise raise UnsupportedFileType."""
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        shown = f"a {extension} file" if extension else "a file with no extension"
        raise UnsupportedFileType(
            f"This is {shown}. Saabit reads CSV or Excel (.xlsx) files, so please export "
            "your orders in one of those formats and upload that."
        )
    return extension


def save_upload(stream: BinaryIO, dest: Path) -> int:
    """Copy an upload to dest in 1 MB chunks; stop and delete it once it passes 25 MB."""
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := stream.read(CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise too_large()
                out.write(chunk)
    except FileTooLarge:
        dest.unlink(missing_ok=True)
        raise
    return size


def read_table(path: Path, filename: str, work_dir: Path) -> Table:
    """Inspect an uploaded file on disk, enforcing the 25 MB and 500,000-row limits.

    filename is the user's name for the file and is only used for its extension.
    work_dir receives a UTF-8 copy when the file is not UTF-8.
    """
    extension = extension_of(filename)
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise too_large()
    table = read_xlsx(path) if extension == ".xlsx" else read_csv(path, work_dir)
    if table.rows > MAX_ROWS:
        raise TooManyRows("The file has more than 500,000 rows; the limit is 500,000.")
    return table


def read_bundled_file(path: Path, work_dir: Path, columns: list[str] | None = None) -> Table:
    """Inspect a file shipped with the app (the sample). gzip allowed; no upload size limit."""
    extension_of(path.name.removesuffix(GZIP_SUFFIX))
    return read_csv(path, work_dir, columns)


def opener_for(path: Path) -> Callable[..., IO[bytes]]:
    """gzip.open for .gz files, plain open otherwise; both stream from disk."""
    if path.name.endswith(GZIP_SUFFIX):
        return gzip.open
    return open


def read_csv(path: Path, work_dir: Path, columns: list[str] | None = None) -> Table:
    """Check, decode, sniff and count a CSV without loading the whole file."""
    opener = opener_for(path)
    with opener(path, "rb") as f:
        start = f.read(SNIFF_BYTES)
    if not start.strip():
        raise EmptyFile("The file is empty.")
    if start.startswith(BINARY_SIGNATURES) or b"\x00" in start[:8192]:
        raise UnreadableFile(
            "This file is named .csv but is not a text CSV (it may be a PDF, image or "
            "Excel file). Please upload the original CSV or Excel export."
        )
    encoding = detect_encoding(path)
    if encoding != "utf-8":
        path = transcode_to_utf8(path, encoding, work_dir / UTF8_COPY)
    delimiter = sniff_delimiter(start.decode(encoding, errors="replace"))
    rows = count_rows(path, delimiter)
    if rows == 0:
        raise EmptyFile("The file has a header row but no data rows.")
    all_columns, head = read_head(path, delimiter, columns)
    return Table(rows=rows, columns=all_columns, head=head, encoding=encoding)


def detect_encoding(path: Path) -> str:
    """'utf-8' if the whole file decodes as UTF-8 (checked chunk by chunk), else 'latin-1'."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    with opener_for(path)(path, "rb") as f:
        try:
            while chunk := f.read(CHUNK_BYTES):
                decoder.decode(chunk)
            decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            return "latin-1"
    return "utf-8"


def transcode_to_utf8(path: Path, encoding: str, dest: Path) -> Path:
    """Write a UTF-8 copy of a text file in chunks. The original is left untouched."""
    with opener_for(path)(path, "rb") as src, dest.open("w", encoding="utf-8", newline="") as out:
        decoder = codecs.getincrementaldecoder(encoding)()
        while chunk := src.read(CHUNK_BYTES):
            out.write(decoder.decode(chunk))
        out.write(decoder.decode(b"", final=True))
    return dest


def sniff_delimiter(text: str) -> str:
    """Pick the candidate delimiter that appears most often in the header line."""
    header = text.lstrip("﻿").split("\n", 1)[0]
    counts = {delimiter: header.count(delimiter) for delimiter in DELIMITERS}
    best = max(counts, key=lambda delimiter: counts[delimiter])
    return best if counts[best] > 0 else ","


def count_rows(path: Path, delimiter: str) -> int:
    """Data rows in the whole file, counted by DuckDB scanning it from disk."""
    try:
        with duckdb.connect(config=DUCKDB_CONFIG) as con:
            relation = con.read_csv(
                str(path), header=True, sep=delimiter, quotechar='"',
                all_varchar=True, null_padding=True,
            )
            return int(relation.shape[0])
    except duckdb.Error as exc:
        raise UnreadableFile("The CSV could not be read; check that it is a valid export.") from exc


def read_head(
    path: Path, delimiter: str, columns: list[str] | None
) -> tuple[list[str], pd.DataFrame]:
    """All header names (stripped), plus the first HEAD_ROWS rows of the wanted columns.

    pyarrow's streaming reader parses 1 MB blocks and stops once HEAD_ROWS rows are read,
    so memory is the result (Arrow strings) plus one block, whatever the file size.
    """
    try:
        names = [str(c) for c in pd.read_csv(path, sep=delimiter, nrows=0, encoding="utf-8-sig")]
        keep = [n for n in names if columns is None or n.strip() in set(columns)]
        reader = pacsv.open_csv(
            path,
            read_options=pacsv.ReadOptions(column_names=names, skip_rows=1, block_size=CHUNK_BYTES),
            parse_options=pacsv.ParseOptions(
                delimiter=delimiter, newlines_in_values=True, invalid_row_handler=lambda _: "skip"
            ),
            convert_options=pacsv.ConvertOptions(
                column_types={n: pa.string() for n in names}, include_columns=keep,
                strings_can_be_null=True,
            ),
        )
        batches, taken = [], 0
        for batch in reader:
            batches.append(batch.slice(0, HEAD_ROWS - taken))
            taken += batches[-1].num_rows
            if taken >= HEAD_ROWS:
                break
        table = pa.Table.from_batches(batches, schema=reader.schema)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, pa.ArrowInvalid, ValueError) as exc:
        raise UnreadableFile("The CSV could not be read; check that it is a valid export.") from exc
    head = table.to_pandas(types_mapper={pa.string(): TEXT_DTYPE}.get)
    head.columns = [c.strip() for c in keep]
    return [n.strip() for n in names], head


def read_xlsx(path: Path) -> Table:
    """Stream the first sheet with openpyxl's read-only mode. Macros are never run."""
    with path.open("rb") as f:
        if f.read(len(XLSX_SIGNATURE)) != XLSX_SIGNATURE:
            raise UnreadableFile("The file is named .xlsx but is not an Excel workbook.")
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, OSError) as exc:
        raise UnreadableFile("The Excel workbook could not be read.") from exc
    try:
        header, head, rows = scan_sheet(workbook.worksheets[0].iter_rows(values_only=True))
    finally:
        workbook.close()
    if rows == 0:
        raise EmptyFile("The file has a header row but no data rows.")
    columns = [str(c).strip() if c is not None else f"Unnamed: {i}" for i, c in enumerate(header)]
    df = pd.DataFrame(head, columns=columns).map(cell_text).astype(TEXT_DTYPE)
    return Table(rows=rows, columns=columns, head=df, encoding="xlsx")


def scan_sheet(rows_iter: Any) -> tuple[tuple, list[tuple], int]:
    """Header row, the first HEAD_ROWS non-blank rows, and the count of all non-blank rows."""
    header = next(rows_iter, None)
    if header is None:
        raise EmptyFile("The file is empty.")
    width, head, count = len(header), [], 0
    for row in rows_iter:
        if all(value is None for value in row):
            continue
        count += 1
        if count <= HEAD_ROWS:
            head.append(tuple(row[:width]) + (None,) * (width - len(row)))
    return header, head, count


def cell_text(value: Any) -> str | None:
    """Excel cell as text, like a CSV export would show it; blank cells stay missing."""
    return None if value is None else str(value)
