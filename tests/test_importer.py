"""Tests for the shared invoice import workflow."""

from pathlib import Path

from src.importer import import_pdf_paths, summarize_results


class DummySession:
    """Placeholder session object for patched import tests."""


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
