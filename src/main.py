"""
CLI entry point for the Deliveroo payslip parser.

Usage:
    python src/main.py <path-to-pdf>
    python src/main.py invoices/*.pdf
"""

import sys
from pathlib import Path

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


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m src.main <path-to-pdf> [<path-to-pdf> ...]")
        sys.exit(1)

    total_earnings = 0.0
    invoice_count = 0

    for pdf_path in sys.argv[1:]:
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


if __name__ == "__main__":
    main()
