"""Shared invoice import workflow for CLI, dashboard uploads, and automation."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from src.db import save_invoice
from src.parser import parse_pdf


@dataclass
class ImportItemResult:
    """Result for a single attempted invoice import."""

    source_name: str
    status: str
    message: str
    serial_number: str | None = None
    total: float | None = None
    archived_path: str | None = None


def import_pdf_paths(
    session,
    pdf_paths: list[str | Path],
    archive_root: str | Path | None = None,
) -> list[ImportItemResult]:
    """Parse and save one or more invoice PDFs."""
    results: list[ImportItemResult] = []

    for pdf_path in pdf_paths:
        path = Path(pdf_path)
        if not path.exists():
            results.append(
                ImportItemResult(
                    source_name=str(pdf_path),
                    status="invalid",
                    message="File not found",
                )
            )
            continue

        if path.suffix.lower() != ".pdf":
            results.append(
                ImportItemResult(
                    source_name=path.name,
                    status="invalid",
                    message="Not a PDF file",
                )
            )
            continue

        results.append(
            _import_single_path(
                session,
                path,
                source_name=path.name,
                archive_root=archive_root,
            )
        )

    return results


def import_uploaded_pdfs(
    session,
    uploaded_files,
    archive_root: str | Path | None = "data/invoices",
) -> list[ImportItemResult]:
    """Parse and save PDFs uploaded through Streamlit."""
    results: list[ImportItemResult] = []

    for uploaded_file in uploaded_files:
        suffix = Path(uploaded_file.name).suffix.lower()
        if suffix != ".pdf":
            results.append(
                ImportItemResult(
                    source_name=uploaded_file.name,
                    status="invalid",
                    message="Not a PDF file",
                )
            )
            continue

        with NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            tmp_path = Path(tmp_file.name)

        try:
            results.append(
                _import_single_path(
                    session,
                    tmp_path,
                    source_name=uploaded_file.name,
                    archive_root=archive_root,
                )
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    return results


def summarize_results(results: list[ImportItemResult]) -> dict[str, int]:
    """Return simple status counts for an import run."""
    summary = {"saved": 0, "duplicate": 0, "error": 0, "invalid": 0}
    for result in results:
        summary[result.status] = summary.get(result.status, 0) + 1
    return summary


def _archive_invoice_pdf(
    pdf_path: Path,
    invoice,
    archive_root: str | Path,
) -> str:
    """Store a copy of the PDF under a stable tax-record folder."""
    root = Path(archive_root)
    subdir = root / str(invoice.invoice_date.year) / f"{invoice.invoice_date.month:02d}"
    subdir.mkdir(parents=True, exist_ok=True)
    archived_path = subdir / f"{invoice.serial_number}.pdf"

    if pdf_path.resolve() != archived_path.resolve():
        shutil.copy2(pdf_path, archived_path)

    return str(archived_path)


def _import_single_path(
    session,
    pdf_path: Path,
    source_name: str,
    archive_root: str | Path | None = None,
) -> ImportItemResult:
    """Parse a single PDF path and save it to the database."""
    try:
        invoice = parse_pdf(pdf_path)
    except (ValueError, FileNotFoundError) as exc:
        return ImportItemResult(
            source_name=source_name,
            status="error",
            message=str(exc),
        )

    archived_path = None
    if archive_root is not None:
        archived_path = _archive_invoice_pdf(pdf_path, invoice, archive_root)

    saved = save_invoice(session, invoice)
    if saved:
        return ImportItemResult(
            source_name=source_name,
            status="saved",
            message="Saved",
            serial_number=invoice.serial_number,
            total=invoice.grand_total,
            archived_path=archived_path,
        )

    return ImportItemResult(
        source_name=source_name,
        status="duplicate",
        message="Skipped duplicate",
        serial_number=invoice.serial_number,
        total=invoice.grand_total,
        archived_path=archived_path,
    )
