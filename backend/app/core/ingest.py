"""Read CSV/XLSX files, handle encodings, and write Parquet."""

import io
import zipfile
from pathlib import Path

import pandas as pd

MAX_BYTES = 25 * 1024 * 1024
MAX_ROWS = 500_000
ALLOWED_EXTENSIONS = (".csv", ".xlsx")
XLSX_SIGNATURE = b"PK\x03\x04"
BINARY_SIGNATURES = (
    b"%PDF", XLSX_SIGNATURE, b"\xd0\xcf\x11\xe0", b"\x89PNG", b"\xff\xd8\xff", b"GIF8",
)
DELIMITERS = (",", ";", "\t", "|")
BINARY_SNIFF_BYTES = 8192


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


def read_upload(data: bytes, filename: str) -> pd.DataFrame:
    """Parse a user upload, enforcing the 25 MB and 500,000-row limits."""
    extension = extension_of(filename)
    if len(data) > MAX_BYTES:
        raise FileTooLarge(
            "The file is over 25 MB, which is the upload limit. "
            "Try exporting a shorter date range."
        )
    df = parse_table(data, extension)
    if len(df) > MAX_ROWS:
        raise TooManyRows("The file has more than 500,000 rows; the limit is 500,000.")
    return df


def read_bundled_file(path: Path) -> pd.DataFrame:
    """Parse a file shipped with the app (the sample). Same parsing, no upload size limit."""
    return parse_table(path.read_bytes(), extension_of(path.name))


def parse_table(data: bytes, extension: str) -> pd.DataFrame:
    """Parse CSV or XLSX bytes into a DataFrame of text cells with stripped headers."""
    if not data.strip():
        raise EmptyFile("The file is empty.")
    df = read_xlsx(data) if extension == ".xlsx" else read_csv(data)
    df.columns = [str(column).strip() for column in df.columns]
    if df.empty:
        raise EmptyFile("The file has a header row but no data rows.")
    return df


def read_csv(data: bytes) -> pd.DataFrame:
    """Decode (UTF-8, then latin-1), sniff the delimiter, and read every cell as text."""
    if data.startswith(BINARY_SIGNATURES) or b"\x00" in data[:BINARY_SNIFF_BYTES]:
        raise UnreadableFile(
            "This file is named .csv but is not a text CSV (it may be a PDF, image or "
            "Excel file). Please upload the original CSV or Excel export."
        )
    text = decode_text(data)
    try:
        return pd.read_csv(
            io.StringIO(text), sep=sniff_delimiter(text), dtype=str, nrows=MAX_ROWS + 1
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise UnreadableFile(f"The CSV could not be read: {exc}") from exc


def read_xlsx(data: bytes) -> pd.DataFrame:
    """Read the first sheet of a real XLSX workbook as text. Macros are never run."""
    if not data.startswith(XLSX_SIGNATURE):
        raise UnreadableFile("The file is named .xlsx but is not an Excel workbook.")
    try:
        return pd.read_excel(
            io.BytesIO(data), sheet_name=0, dtype=str, engine="openpyxl", nrows=MAX_ROWS + 1
        )
    except (zipfile.BadZipFile, ValueError, KeyError) as exc:
        raise UnreadableFile("The Excel workbook could not be read.") from exc


def decode_text(data: bytes) -> str:
    """UTF-8 (a leading BOM is dropped); if that fails, latin-1, which accepts any bytes."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def sniff_delimiter(text: str) -> str:
    """Pick the candidate delimiter that appears most often in the header line."""
    header = text.split("\n", 1)[0]
    counts = {delimiter: header.count(delimiter) for delimiter in DELIMITERS}
    best = max(counts, key=lambda delimiter: counts[delimiter])
    return best if counts[best] > 0 else ","
