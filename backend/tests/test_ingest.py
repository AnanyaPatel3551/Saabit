import pytest

from app.core.ingest import (
    MAX_BYTES,
    MAX_ROWS,
    EmptyFile,
    FileTooLarge,
    TooManyRows,
    UnreadableFile,
    UnsupportedFileType,
    read_upload,
)
from tests.conftest import FIXTURES


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_reads_amazon_csv_with_all_rows() -> None:
    df = read_upload(load("amazon_300.csv"), "amazon_300.csv")

    assert len(df) == 300
    assert "Order ID" in df.columns


def test_strips_whitespace_from_headers() -> None:
    df = read_upload(load("amazon_300.csv"), "amazon_300.csv")

    assert "Sales Channel" in df.columns
    assert "Sales Channel " not in df.columns


def test_reads_every_cell_as_text() -> None:
    df = read_upload(load("amazon_300.csv"), "amazon_300.csv")

    assert df["Amount"].dropna().map(type).eq(str).all()


def test_falls_back_to_latin1_when_file_is_not_utf8() -> None:
    df = read_upload(load("latin1.csv"), "latin1.csv")

    assert len(df) == 21
    assert "Café Crème" in set(df["Category"])
    assert "Müsli" in set(df["Category"])


def test_sniffs_semicolon_delimiter() -> None:
    df = read_upload(load("semicolon.csv"), "semicolon.csv")

    assert list(df.columns) == ["Order ID", "Date", "Amount", "Status", "State"]
    assert len(df) == 20


def test_reads_only_the_first_sheet_of_xlsx() -> None:
    df = read_upload(load("orders.xlsx"), "orders.xlsx")

    assert list(df.columns) == ["Order ID", "Order Date", "Amount", "Status"]
    assert len(df) == 20


def test_extension_check_ignores_case() -> None:
    df = read_upload(load("semicolon.csv"), "SEMICOLON.CSV")

    assert len(df) == 20


def test_rejects_empty_file() -> None:
    with pytest.raises(EmptyFile):
        read_upload(load("empty.csv"), "empty.csv")


def test_rejects_file_with_header_but_no_rows() -> None:
    with pytest.raises(EmptyFile):
        read_upload(b"Order ID,Date,Amount\n", "header_only.csv")


def test_rejects_oversized_file() -> None:
    with pytest.raises(FileTooLarge, match="25 MB"):
        read_upload(b"x" * (MAX_BYTES + 1), "big.csv")


def test_accepts_file_exactly_at_size_limit() -> None:
    data = b"a\n" + b"x" * (MAX_BYTES - 3) + b"\n"
    assert len(data) == MAX_BYTES

    df = read_upload(data, "at_limit.csv")

    assert len(df) == 1


def test_rejects_more_than_500000_rows() -> None:
    data = b"a\n" + b"1\n" * (MAX_ROWS + 1)

    with pytest.raises(TooManyRows, match="500,000"):
        read_upload(data, "many_rows.csv")


def test_accepts_exactly_500000_rows() -> None:
    data = b"a\n" + b"1\n" * MAX_ROWS

    assert len(read_upload(data, "max_rows.csv")) == MAX_ROWS


@pytest.mark.parametrize("filename", ["orders.json", "orders.xls", "orders", "orders.csv.exe"])
def test_rejects_other_extensions(filename: str) -> None:
    with pytest.raises(UnsupportedFileType):
        read_upload(b"a,b\n1,2\n", filename)


def test_rejects_xlsx_that_is_not_really_a_workbook() -> None:
    with pytest.raises(UnreadableFile):
        read_upload(b"Order ID,Date\n1,2\n", "renamed.xlsx")


@pytest.mark.parametrize(
    "signature",
    [b"%PDF-1.4\n", b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"\x89PNG\r\n", b"\xff\xd8\xff", b"GIF89a"],
)
def test_rejects_known_binary_formats_renamed_to_csv(signature: bytes) -> None:
    with pytest.raises(UnreadableFile):
        read_upload(signature + b"1 0 obj << /Type /Catalog >> endobj\n", "renamed.csv")


def test_unsupported_type_message_names_the_formats_a_seller_knows() -> None:
    with pytest.raises(UnsupportedFileType, match="CSV or Excel"):
        read_upload(b"%PDF-1.4\n", "invoice.pdf")


def test_rejects_binary_data_named_csv() -> None:
    with pytest.raises(UnreadableFile):
        read_upload(load("orders.xlsx"), "sneaky.csv")
