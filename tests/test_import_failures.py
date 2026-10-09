"""Import failure recovery and temporary-file cleanup regressions."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pdfminer.pdfparser import PDFSyntaxError
from sqlalchemy.exc import SQLAlchemyError

from src import importer


@pytest.fixture
def invoice():
    return SimpleNamespace(
        serial_number="test_invoice", invoice_date=date(2026, 3, 24), grand_total=10.0
    )


@pytest.fixture
def pdf_paths(tmp_path):
    paths = [tmp_path / name for name in ("first.pdf", "second.pdf")]
    for path in paths:
        path.write_bytes(b"mock invoice")
    return paths


def test_database_failure_rolls_back_and_continues(monkeypatch, pdf_paths, invoice):
    session = Mock()
    monkeypatch.setattr(importer, "parse_pdf", Mock(return_value=invoice))
    attempts = []

    def save(db_session, parsed):
        attempts.append(parsed)
        if len(attempts) == 1:
            raise SQLAlchemyError("Database unavailable")
        db_session.rollback.assert_called_once_with()
        return True

    monkeypatch.setattr(importer, "save_invoice", save)
    results = importer.import_pdf_paths(session, pdf_paths)

    assert [result.status for result in results] == ["error", "saved"]
    assert "Database unavailable" in results[0].message
    assert len(attempts) == 2
    session.rollback.assert_called_once_with()


def test_archive_failure_does_not_save_failed_invoice(monkeypatch, tmp_path, pdf_paths, invoice):
    monkeypatch.setattr(importer, "parse_pdf", Mock(return_value=invoice))
    monkeypatch.setattr(importer, "_archive_invoice_pdf", Mock(side_effect=[
        PermissionError("Archive is read-only"), str(tmp_path / "archived.pdf")
    ]))
    save = Mock(return_value=True)
    monkeypatch.setattr(importer, "save_invoice", save)
    session = Mock()

    results = importer.import_pdf_paths(session, pdf_paths, archive_root=tmp_path)

    assert [result.status for result in results] == ["error", "saved"]
    assert "Archive is read-only" in results[0].message
    save.assert_called_once_with(session, invoice)


def test_corrupt_pdf_does_not_stop_next_import(monkeypatch, pdf_paths, invoice):
    actual_parse = importer.parse_pdf

    def parse(path):
        if path == pdf_paths[0]:
            return actual_parse(path)  # Exercise the real PDF reader on invalid bytes.
        return invoice

    monkeypatch.setattr(importer, "parse_pdf", parse)
    save = Mock(return_value=True)
    monkeypatch.setattr(importer, "save_invoice", save)
    session = Mock()

    results = importer.import_pdf_paths(session, pdf_paths)

    assert [result.status for result in results] == ["error", "saved"]
    assert results[0].message
    save.assert_called_once_with(session, invoice)


def test_upload_temp_file_removed_after_database_failure(monkeypatch, invoice):
    paths = []

    def parse(path):
        paths.append(path)
        assert path.exists()
        return invoice

    monkeypatch.setattr(importer, "parse_pdf", parse)
    monkeypatch.setattr(importer, "save_invoice", Mock(side_effect=SQLAlchemyError("Save failed")))
    upload = SimpleNamespace(name="invoice.pdf", getbuffer=lambda: b"mock invoice")

    try:
        results = importer.import_uploaded_pdfs(Mock(), [upload], archive_root=None)
    except SQLAlchemyError:
        pass  # Cleanup must work whether failures propagate or become error results.
    else:
        assert results[0].status == "error"

    assert len(paths) == 1
    assert not paths[0].exists()
