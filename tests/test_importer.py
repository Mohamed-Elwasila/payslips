"""Tests for the shared invoice import workflow."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.importer import import_pdf_paths, import_uploaded_pdfs, summarize_results


class DummySession:
    """Placeholder session object for patched import tests."""


def test_mixed_batch_continues_after_parse_error(monkeypatch, tmp_path):
    bad_pdf = tmp_path / "bad.pdf"
    good_pdf = tmp_path / "good.PDF"
    bad_pdf.write_bytes(b"bad")
    good_pdf.write_bytes(b"good")
    invoice = SimpleNamespace(serial_number="valid", grand_total=12.34)
    parse = Mock(side_effect=[ValueError("Invalid invoice"), invoice])
    save = Mock(return_value=True)
    monkeypatch.setattr("src.importer.parse_pdf", parse)
    monkeypatch.setattr("src.importer.save_invoice", save)
    session = DummySession()

    results = import_pdf_paths(session, [tmp_path / "missing.pdf", bad_pdf, good_pdf])

    assert [result.status for result in results] == ["invalid", "error", "saved"]
    assert results[1].message == "Invalid invoice"
    assert results[2].serial_number == "valid"
    save.assert_called_once_with(session, invoice)


@pytest.mark.parametrize("parse_error", [False, True])
def test_uploaded_temp_file_is_removed(monkeypatch, tmp_path, parse_error):
    parsed_paths = []
    content = b"uploaded invoice"
    upload = SimpleNamespace(name="invoice.pdf", getbuffer=lambda: content)

    def parse(path):
        parsed_paths.append(path)
        assert path.read_bytes() == content
        if parse_error:
            raise ValueError("Invalid invoice")
        return SimpleNamespace(serial_number="upload", grand_total=1.0)

    save = Mock(return_value=True)
    monkeypatch.setattr("src.importer.parse_pdf", parse)
    monkeypatch.setattr("src.importer.save_invoice", save)

    results = import_uploaded_pdfs(DummySession(), [upload], archive_root=None)

    assert results[0].status == ("error" if parse_error else "saved")
    assert len(parsed_paths) == 1
    assert not parsed_paths[0].exists()
    assert save.call_count == (0 if parse_error else 1)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Importer overwrites the archive before checking for a duplicate",
)
def test_duplicate_preserves_original_archive(monkeypatch, tmp_path):
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"original invoice")
    invoice = SimpleNamespace(
        serial_number="same_invoice", grand_total=1.0, invoice_date=date(2026, 3, 24)
    )
    monkeypatch.setattr("src.importer.parse_pdf", lambda _: invoice)
    monkeypatch.setattr("src.importer.save_invoice", Mock(side_effect=[True, False]))
    session = DummySession()
    archive = tmp_path / "archive"

    first = import_pdf_paths(session, [source], archive_root=archive)[0]
    source.write_bytes(b"different invoice with same serial")
    second = import_pdf_paths(session, [source], archive_root=archive)[0]

    assert first.status == "saved"
    assert second.status == "duplicate"
    assert Path(first.archived_path).read_bytes() == b"original invoice"


@pytest.mark.parametrize("absolute", [False, True], ids=["parent-traversal", "absolute"])
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Importer uses an unchecked invoice serial number as an archive path",
)
def test_unsafe_serial_cannot_overwrite_file_outside_archive(monkeypatch, tmp_path, absolute):
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"incoming invoice")
    outside = tmp_path / "protected.pdf"
    outside.write_bytes(b"keep this file")
    serial = str(outside.with_suffix("")) if absolute else "../../../protected"
    invoice = SimpleNamespace(
        serial_number=serial, grand_total=1.0, invoice_date=date(2026, 3, 24)
    )
    monkeypatch.setattr("src.importer.parse_pdf", lambda _: invoice)
    monkeypatch.setattr("src.importer.save_invoice", Mock(return_value=True))

    try:
        import_pdf_paths(DummySession(), [source], archive_root=tmp_path / "archive")
    except ValueError:
        pass  # Rejecting the unsafe serial is also an acceptable outcome.

    assert outside.read_bytes() == b"keep this file"


def test_import_pdf_paths_reports_missing_file(tmp_path):
    session = DummySession()

    results = import_pdf_paths(session, [tmp_path / "missing.pdf"])

    assert len(results) == 1
    assert results[0].status == "invalid"
    assert results[0].message == "File not found"


def test_import_pdf_paths_reports_non_pdf(tmp_path):
    session = DummySession()
    txt_file = tmp_path / "note.txt"
    txt_file.write_text("not a pdf", encoding="utf-8")

    results = import_pdf_paths(session, [txt_file])

    assert len(results) == 1
    assert results[0].status == "invalid"
    assert results[0].message == "Not a PDF file"


def test_import_pdf_paths_saved(monkeypatch, tmp_path):
    session = DummySession()
    pdf_file = tmp_path / "invoice.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")

    class Invoice:
        serial_number = "ri_test_saved"
        grand_total = 12.34

    monkeypatch.setattr("src.importer.parse_pdf", lambda _: Invoice())
    monkeypatch.setattr("src.importer.save_invoice", lambda _session, _invoice: True)

    results = import_pdf_paths(session, [pdf_file])

    assert len(results) == 1
    assert results[0].status == "saved"
    assert results[0].serial_number == "ri_test_saved"
    assert results[0].total == 12.34


def test_import_pdf_paths_duplicate(monkeypatch, tmp_path):
    session = DummySession()
    pdf_file = tmp_path / "invoice.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")

    class Invoice:
        serial_number = "ri_test_duplicate"
        grand_total = 45.67

    monkeypatch.setattr("src.importer.parse_pdf", lambda _: Invoice())
    monkeypatch.setattr("src.importer.save_invoice", lambda _session, _invoice: False)

    results = import_pdf_paths(session, [pdf_file])

    assert len(results) == 1
    assert results[0].status == "duplicate"
    assert results[0].message == "Skipped duplicate"


def test_import_pdf_paths_parse_error(monkeypatch, tmp_path):
    session = DummySession()
    pdf_file = tmp_path / "invoice.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")

    def _raise(_path: Path):
        raise ValueError("Could not parse invoice")

    monkeypatch.setattr("src.importer.parse_pdf", _raise)

    results = import_pdf_paths(session, [pdf_file])

    assert len(results) == 1
    assert results[0].status == "error"
    assert results[0].message == "Could not parse invoice"


def test_import_pdf_paths_archives_pdf(monkeypatch, tmp_path):
    session = DummySession()
    pdf_file = tmp_path / "invoice.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 archive me")
    archive_root = tmp_path / "archive"

    class Invoice:
        serial_number = "ri_test_archive"
        grand_total = 19.99
        invoice_date = date(2026, 3, 24)

    monkeypatch.setattr("src.importer.parse_pdf", lambda _: Invoice())
    monkeypatch.setattr("src.importer.save_invoice", lambda _session, _invoice: True)

    results = import_pdf_paths(session, [pdf_file], archive_root=archive_root)

    archived_path = archive_root / "2026" / "03" / "ri_test_archive.pdf"
    assert results[0].archived_path == str(archived_path)
    assert archived_path.read_bytes() == b"%PDF-1.4 archive me"


def test_import_uploaded_pdfs_archives_before_temp_cleanup(monkeypatch, tmp_path):
    session = DummySession()
    archive_root = tmp_path / "archive"

    class UploadedFile:
        name = "upload.pdf"

        @staticmethod
        def getbuffer():
            return b"%PDF-1.4 from upload"

    class Invoice:
        serial_number = "ri_test_upload_archive"
        grand_total = 8.5
        invoice_date = date(2026, 3, 30)

    monkeypatch.setattr("src.importer.parse_pdf", lambda _: Invoice())
    monkeypatch.setattr("src.importer.save_invoice", lambda _session, _invoice: True)

    results = import_uploaded_pdfs(
        session,
        [UploadedFile()],
        archive_root=archive_root,
    )

    archived_path = archive_root / "2026" / "03" / "ri_test_upload_archive.pdf"
    assert results[0].archived_path == str(archived_path)
    assert archived_path.read_bytes() == b"%PDF-1.4 from upload"


def test_summarize_results_counts_statuses():
    results = [
        type("Result", (), {"status": "saved"})(),
        type("Result", (), {"status": "saved"})(),
        type("Result", (), {"status": "duplicate"})(),
        type("Result", (), {"status": "error"})(),
        type("Result", (), {"status": "invalid"})(),
    ]

    summary = summarize_results(results)

    assert summary == {
        "saved": 2,
        "duplicate": 1,
        "error": 1,
        "invalid": 1,
    }
