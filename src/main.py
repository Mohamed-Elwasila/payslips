"""
CLI entry point for the Deliveroo payslip parser.

Usage:
    python -m src.main parse <path-to-pdf> [<path-to-pdf> ...]
    python -m src.main save <path-to-pdf> [<path-to-pdf> ...]
    python -m src.main fetch
    python -m src.main summary [year]
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

from src.importer import import_pdf_paths, summarize_results
from src.parser import parse_pdf


def print_invoice(pdf_path: str) -> None:
    """Parse and display a single invoice."""
    path = Path(pdf_path)
    if not path.exists():
        print(f"Error: File not found: {pdf_path}")
        return
    if not path.suffix.lower() == ".pdf":
        print(f"Error: Not a PDF file: {pdf_path}")
        return

    try:
        invoice = parse_pdf(path)
    except ValueError as e:
        print(f"Error parsing {pdf_path}: {e}")
        return

    print(f"\n{'=' * 50}")
    print(f"Invoice: {invoice.serial_number}")
    print(f"Period:  {invoice.period_start} to {invoice.period_end}")
    print(f"Date:    {invoice.invoice_date}")
    print(f"{'=' * 50}")

    print(f"\n{'Day':<12} {'Date':<16} {'Orders':<8} {'Total':>8}")
    print(f"{'-' * 12} {'-' * 16} {'-' * 8} {'-' * 8}")
    for d in invoice.deliveries:
        print(f"{d.day:<12} {d.date!s:<16} {d.orders_delivered:<8} £{d.total:>7.2f}")

    print(f"\n{'Deliveries:':<20} £{invoice.deliveries_total:>7.2f}")
    print(f"{'Adjustments:':<20} £{invoice.adjustments:>7.2f}")
    print(f"{'Tips:':<20} £{invoice.tips:>7.2f}")
    print(f"{'TOTAL:':<20} £{invoice.grand_total:>7.2f}")
    print()


def cmd_parse(args: list[str]) -> None:
    """Parse and display PDFs (no database)."""
    if not args:
        print("Usage: python -m src.main parse <path-to-pdf> [...]")
        return

    total_earnings = 0.0
    invoice_count = 0

    for pdf_path in args:
        print_invoice(pdf_path)
        try:
            invoice = parse_pdf(pdf_path)
            total_earnings += invoice.grand_total
            invoice_count += 1
        except (ValueError, FileNotFoundError):
            pass

    if invoice_count > 1:
        print(f"{'=' * 50}")
        print(f"Total across {invoice_count} invoices: £{total_earnings:.2f}")
        print(f"{'=' * 50}")


def cmd_save(args: list[str]) -> None:
    """Parse PDFs and save to the database."""
    if not args:
        print("Usage: python -m src.main save <path-to-pdf> [...]")
        return

    from src.db import get_session, init_db

    init_db()
    session = get_session()

    try:
        results = import_pdf_paths(session, args, archive_root="data/invoices")
        summary = summarize_results(results)
        for result in results:
            if result.status == "saved":
                print(
                    f"Saved: {result.serial_number} "
                    f"({result.total:.2f})"
                )
            elif result.status == "duplicate":
                print(f"Skipped (duplicate): {result.serial_number}")
            else:
                print(f"Skipping: {result.source_name}: {result.message}")

        if any(result.archived_path for result in results):
            print(f"Archived PDFs under: {Path('data/invoices').resolve()}")

        print(
            "\nDone: "
            f"{summary['saved']} saved, "
            f"{summary['duplicate']} duplicates, "
            f"{summary['error']} parse errors, "
            f"{summary['invalid']} invalid files"
        )
    finally:
        session.close()


def _print_summary_table(rows, title: str = None, total_label: str = None, total: float = None):
    """Print a formatted summary table."""
    month_names = [
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]

    if title:
        print(f"\n{title}")
    print(f"\n{'Month':<20} {'Invoices':<10} {'Earned':>10}")
    print(f"{'-' * 20} {'-' * 10} {'-' * 10}")

    for row in rows:
        month_name = f"{month_names[row['month']]} {row['year']}"
        print(
            f"{month_name:<20} {row['invoice_count']:<10} "
            f"£{row['total_earned']:>9.2f}"
        )

    if total is not None and total_label:
        print(f"\n{'=' * 42}")
        print(f"{total_label}: £{total:.2f}")
        print(f"{'=' * 42}")


def cmd_summary(args: list[str]) -> None:
    """Show earnings summary from the database."""
    from src.db import (
        get_session, get_summary, get_yearly_total,
        get_summary_by_tax_year, get_tax_year_total,
    )

    session = get_session()

    try:
        tax_mode = "--tax" in args
        filtered_args = [a for a in args if a != "--tax"]
        year = int(filtered_args[0]) if filtered_args else None

        if tax_mode:
            if not year:
                print("Usage: python -m src.main summary --tax <start_year>")
                print("Example: python -m src.main summary --tax 2025  (tax year 2025/2026)")
                return

            rows = get_summary_by_tax_year(session, year)
            if not rows:
                print(f"No invoices found for tax year {year}/{year + 1}.")
                return

            total = get_tax_year_total(session, year)
            _print_summary_table(
                rows,
                title=f"Tax Year {year}/{year + 1} (6 Apr {year} - 5 Apr {year + 1})",
                total_label=f"Total for tax year {year}/{year + 1}",
                total=total,
            )
        else:
            rows = get_summary(session, year)
            if not rows:
                print("No invoices found in the database.")
                return

            if year:
                total = get_yearly_total(session, year)
                _print_summary_table(rows, total_label=f"Total for {year}", total=total)
            else:
                grand = sum(r["total_earned"] for r in rows)
                _print_summary_table(rows, total_label="Grand total", total=grand)
    finally:
        session.close()


def cmd_fetch(args: list[str]) -> None:
    """Fetch Deliveroo invoices from Gmail, parse, and save to database."""
    from src.email_fetcher import fetch_invoices
    from src.db import get_latest_invoice_date, get_session, init_db

    output_dir = args[0] if args else None
    fetch_lookback_days = int(os.getenv("FETCH_LOOKBACK_DAYS", "35"))
    latest_invoice_date = None

    init_db()
    session = get_session()

    try:
        latest_invoice_date = get_latest_invoice_date(session)
    finally:
        session.close()

    after_date = None
    if latest_invoice_date is not None:
        after_date = latest_invoice_date - timedelta(days=fetch_lookback_days)
        print(
            "Searching Gmail for recent invoices "
            f"after {after_date.isoformat()} "
            f"(latest saved invoice: {latest_invoice_date.isoformat()})."
        )
    else:
        print("No saved invoices yet. Searching Gmail for available Deliveroo invoices.")

    pdfs = fetch_invoices(output_dir=output_dir, after_date=after_date)

    if not pdfs:
        return

    session = get_session()

    try:
        results = import_pdf_paths(
            session,
            pdfs,
            archive_root="data/invoices",
        )
        summary = summarize_results(results)
        for result in results:
            if result.status == "saved":
                print(
                    f"Saved: {result.serial_number} "
                    f"({result.total:.2f})"
                )
            elif result.status == "duplicate":
                print(f"Skipped (duplicate): {result.serial_number}")
            else:
                print(f"Skipping: {result.source_name}: {result.message}")

        saved_or_archived = [
            result.archived_path
            for result in results
            if result.archived_path is not None
        ]
        if saved_or_archived:
            print(f"Archived PDFs under: {Path('data/invoices').resolve()}")

        print(
            "\nDone: "
            f"{summary['saved']} saved, "
            f"{summary['duplicate']} duplicates, "
            f"{summary['error']} parse errors, "
            f"{summary['invalid']} invalid files"
        )
    finally:
        session.close()


COMMANDS = {
    "parse": cmd_parse,
    "save": cmd_save,
    "fetch": cmd_fetch,
    "summary": cmd_summary,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: python -m src.main <command> [args]")
        print()
        print("Commands:")
        print("  parse   <pdf> [...]   Parse and display invoice PDFs")
        print("  save    <pdf> [...]   Parse and save invoices to database")
        print("  fetch   [output_dir]  Fetch invoices from Gmail and save to DB")
        print("  summary [year]        Show earnings summary (calendar year)")
        print("  summary --tax <year>  Show earnings by UK tax year")
        sys.exit(1)

    command = sys.argv[1]
    COMMANDS[command](sys.argv[2:])


if __name__ == "__main__":
    main()
