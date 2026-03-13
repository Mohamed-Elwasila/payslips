"""Shared invoice import workflow for CLI, dashboard uploads, and automation."""

from __future__ import annotations

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


def import_pdf_paths(session, pdf_paths: list[str | Path]) -> list[ImportItemResult]:
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

        results.append(_import_single_path(session, path, source_name=path.name))

    return results


def import_uploaded_pdfs(session, uploaded_files) -> list[ImportItemResult]:
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
                _import_single_path(session, tmp_path, source_name=uploaded_file.name)
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


def _import_single_path(session, pdf_path: Path, source_name: str) -> ImportItemResult:
    """Parse a single PDF path and save it to the database."""
    try:
        invoice = parse_pdf(pdf_path)
    except (ValueError, FileNotFoundError) as exc:
        return ImportItemResult(
            source_name=source_name,
            status="error",
            message=str(exc),
        )

    saved = save_invoice(session, invoice)
    if saved:
        return ImportItemResult(
            source_name=source_name,
            status="saved",
            message="Saved",
            serial_number=invoice.serial_number,
            total=invoice.grand_total,
        )

    return ImportItemResult(
        source_name=source_name,
        status="duplicate",
        message="Skipped duplicate",
        serial_number=invoice.serial_number,
        total=invoice.grand_total,
    )
