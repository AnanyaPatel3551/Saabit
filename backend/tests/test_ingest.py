import io
from pathlib import Path

import pandas as pd
import pytest

from app.core.ingest import (
    HEAD_ROWS,
    MAX_BYTES,
    MAX_ROWS,
    TEXT_DTYPE,
    EmptyFile,
    FileTooLarge,
    Table,
    TooManyRows,
    UnreadableFile,
    UnsupportedFileType,
    read_bundled_file,
    read_table,
    save_upload,
)
from tests.conftest import FIXTURES


def read_fixture(name: str, tmp_path: Path, filename: str | None = None) -> Table:
    return read_table(FIXTURES / name, filename or name, tmp_path)


def read_bytes(data: bytes, filename: str, tmp_path: Path) -> Table:
    path = tmp_path / "upload.bin"
    path.write_bytes(data)
    return read_table(path, filename, tmp_path)


class RepeatingStream(io.RawIOBase):
    """A readable stream of `total` bytes that never holds more than one chunk."""

    def __init__(self, total: int) -> None:
        self.remaining = total
        self.largest_read = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        size = self.remaining if size < 0 else min(size, self.remaining)
        self.remaining -= size
        self.largest_read = max(self.largest_read, size)
        return b"x" * size


def test_reads_amazon_csv_with_all_rows(tmp_path: Path) -> None:
    table = read_fixture("amazon_300.csv", tmp_path)

    assert table.rows == 300
    assert len(table.head) == 300
    assert "Order ID" in table.columns


def test_strips_whitespace_from_headers(tmp_path: Path) -> None:
    table = read_fixture("amazon_300.csv", tmp_path)

    assert "Sales Channel" in table.columns
    assert "Sales Channel" in table.head.columns
    assert "Sales Channel " not in table.columns


def test_reads_every_cell_as_pyarrow_text(tmp_path: Path) -> None:
    head = read_fixture("amazon_300.csv", tmp_path).head

    assert all(dtype == TEXT_DTYPE for dtype in head.dtypes)
    assert head["Amount"].dropna().map(type).eq(str).all()


def test_falls_back_to_latin1_when_file_is_not_utf8(tmp_path: Path) -> None:
    table = read_fixture("latin1.csv", tmp_path)

    assert table.rows == 21
    assert table.encoding == "latin-1"
    assert "Café Crème" in set(table.head["Category"])
    assert "Müsli" in set(table.head["Category"])


def test_latin1_file_is_converted_to_a_utf8_working_copy(tmp_path: Path) -> None:
    read_fixture("latin1.csv", tmp_path)

    working = (tmp_path / "utf8.csv").read_text(encoding="utf-8")
    assert "Café Crème" in working


def test_sniffs_semicolon_delimiter(tmp_path: Path) -> None:
    table = read_fixture("semicolon.csv", tmp_path)

    assert table.columns == ["Order ID", "Date", "Amount", "Status", "State"]
    assert table.rows == 20


def test_reads_only_the_first_sheet_of_xlsx(tmp_path: Path) -> None:
    table = read_fixture("orders.xlsx", tmp_path)

    assert table.columns == ["Order ID", "Order Date", "Amount", "Status"]
    assert table.rows == 20
    assert table.head["Amount"].iloc[0] == "150"


def test_extension_check_ignores_case(tmp_path: Path) -> None:
    assert read_fixture("semicolon.csv", tmp_path, filename="SEMICOLON.CSV").rows == 20


def test_row_count_covers_the_whole_file_but_head_stops_at_50000(tmp_path: Path) -> None:
    rows = HEAD_ROWS + 10_000
    data = b"Order ID,Amount\n" + b"".join(b"A-%d,%d.5\n" % (i, i) for i in range(rows))

    table = read_bytes(data, "big.csv", tmp_path)

    assert table.rows == rows
    assert len(table.head) == HEAD_ROWS


def test_rejects_empty_file(tmp_path: Path) -> None:
    with pytest.raises(EmptyFile):
        read_fixture("empty.csv", tmp_path)


def test_rejects_file_with_header_but_no_rows(tmp_path: Path) -> None:
    with pytest.raises(EmptyFile):
        read_bytes(b"Order ID,Date,Amount\n", "header_only.csv", tmp_path)


def test_rejects_oversized_file(tmp_path: Path) -> None:
    with pytest.raises(FileTooLarge, match="25 MB"):
        read_bytes(b"x" * (MAX_BYTES + 1), "big.csv", tmp_path)


def test_accepts_file_exactly_at_size_limit(tmp_path: Path) -> None:
    header = b"a\n"
    row = b"x" * 99 + b"\n"
    rows, remainder = divmod(MAX_BYTES - len(header), len(row))
    data = header + row * rows + b"y" * (remainder - 1) + b"\n"
    assert len(data) == MAX_BYTES

    assert read_bytes(data, "at_limit.csv", tmp_path).rows == rows + 1


def test_rejects_more_than_500000_rows(tmp_path: Path) -> None:
    with pytest.raises(TooManyRows, match="500,000"):
        read_bytes(b"a\n" + b"1\n" * (MAX_ROWS + 1), "many_rows.csv", tmp_path)


def test_accepts_exactly_500000_rows(tmp_path: Path) -> None:
    table = read_bytes(b"a\n" + b"1\n" * MAX_ROWS, "max_rows.csv", tmp_path)

    assert table.rows == MAX_ROWS
    assert len(table.head) == HEAD_ROWS


@pytest.mark.parametrize(
    "filename", ["orders.json", "orders.xls", "orders", "orders.csv.exe", "orders.csv.gz"]
)
def test_rejects_other_extensions(filename: str, tmp_path: Path) -> None:
    with pytest.raises(UnsupportedFileType):
        read_bytes(b"a,b\n1,2\n", filename, tmp_path)


def test_unsupported_type_message_names_the_formats_a_seller_knows(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedFileType, match="CSV or Excel"):
        read_bytes(b"%PDF-1.4\n", "invoice.pdf", tmp_path)


def test_rejects_xlsx_that_is_not_really_a_workbook(tmp_path: Path) -> None:
    with pytest.raises(UnreadableFile):
        read_bytes(b"Order ID,Date\n1,2\n", "renamed.xlsx", tmp_path)


@pytest.mark.parametrize(
    "signature",
    [b"%PDF-1.4\n", b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"\x89PNG\r\n", b"\xff\xd8\xff", b"GIF89a"],
)
def test_rejects_known_binary_formats_renamed_to_csv(signature: bytes, tmp_path: Path) -> None:
    with pytest.raises(UnreadableFile):
        read_bytes(signature + b"1 0 obj << /Type /Catalog >> endobj\n", "renamed.csv", tmp_path)


def test_rejects_binary_data_named_csv(tmp_path: Path) -> None:
    with pytest.raises(UnreadableFile):
        read_fixture("orders.xlsx", tmp_path, filename="sneaky.csv")


def test_save_upload_writes_the_exact_bytes(tmp_path: Path) -> None:
    original = (FIXTURES / "latin1.csv").read_bytes()
    dest = tmp_path / "raw.csv"

    size = save_upload(io.BytesIO(original), dest)

    assert size == len(original)
    assert dest.read_bytes() == original


def test_save_upload_streams_in_chunks_and_stops_past_the_limit(tmp_path: Path) -> None:
    stream = RepeatingStream(MAX_BYTES * 3)
    dest = tmp_path / "raw.csv"

    with pytest.raises(FileTooLarge):
        save_upload(stream, dest)

    assert not dest.exists()
    assert stream.largest_read <= 1024 * 1024
    assert stream.remaining > 0


def test_reads_gzipped_bundled_file(tmp_path: Path) -> None:
    table = read_bundled_file(FIXTURES / "amazon_300.csv.gz", tmp_path)

    assert table.rows == 300
    assert "Sales Channel" in table.columns


def test_bundled_read_loads_only_the_requested_columns(tmp_path: Path) -> None:
    table = read_bundled_file(
        FIXTURES / "amazon_300.csv.gz", tmp_path, columns=["Order ID", "Sales Channel"]
    )

    assert list(table.head.columns) == ["Order ID", "Sales Channel"]
    assert len(table.columns) == 24
    assert isinstance(table.head, pd.DataFrame)
