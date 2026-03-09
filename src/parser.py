"""
Deliveroo self-billing invoice PDF parser.

Extracts invoice metadata and delivery line items from Deliveroo PDFs
using pdfplumber for text extraction and regex for structured parsing.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pdfplumber


@dataclass
class Delivery:
    day: str
    date: date
    orders_delivered: int
    total: float


@dataclass
class Invoice:
    serial_number: str
    period_start: date
    period_end: date
    invoice_date: date
    deliveries: list[Delivery]
    deliveries_total: float
    adjustments: float
    tips: float
    grand_total: float


def extract_text(pdf_path: str | Path) -> str: # pdf_path can be a string or a Path object
    """Open a PDF and extract all text from all pages."""
    with pdfplumber.open(pdf_path) as pdf:
        pages_text = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages_text)


def _parse_date(date_str: str) -> date:
    """Parse a date string like '17 February 2026' into a date object."""
    return datetime.strptime(date_str.strip(), "%d %B %Y").date()


def parse_invoice(text: str) -> Invoice:
    """
    Parse extracted PDF text into a structured Invoice object.

    Raises ValueError if required fields cannot be found.
    """
    # Invoice serial number
    serial_match = re.search(r"Invoice serial number:\s*(.+)", text)
    if not serial_match:
        raise ValueError("Could not find invoice serial number")
    serial_number = serial_match.group(1).strip()

    # Invoice period
    period_match = re.search(
        r"Invoice period:\s*(\d{1,2} \w+ \d{4})\s*-\s*(\d{1,2} \w+ \d{4})", text
    )
    if not period_match:
        raise ValueError("Could not find invoice period")
    period_start = _parse_date(period_match.group(1))
    period_end = _parse_date(period_match.group(2))

    # Invoice date
    date_match = re.search(r"Invoice Date:\s*(\d{1,2} \w+ \d{4})", text)
    if not date_match:
        raise ValueError("Could not find invoice date")
    invoice_date = _parse_date(date_match.group(1))

    # Delivery rows: "Tuesday 17 February 2026 1 £4.51"
    delivery_pattern = re.compile(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
        r"(\d{1,2} \w+ \d{4})\s+"
        r"(\d+)\s+"
        r"£([\d,]+\.\d{2})"
    )
    deliveries = []
    for match in delivery_pattern.finditer(text):
        deliveries.append(
            Delivery(
                day=match.group(1),
                date=_parse_date(match.group(2)),
                orders_delivered=int(match.group(3)),
                total=float(match.group(4).replace(",", "")),
            )
        )

    # Totals from the "Invoice Total" section
    # Deliveries total
    deliveries_total_match = re.search(
        r"Deliveries\s+£([\d,]+\.\d{2})\s+£([\d,]+\.\d{2})", text
    )
    deliveries_total = 0.0
    if deliveries_total_match:
        deliveries_total = float(
            deliveries_total_match.group(1).replace(",", "")
        )

    # Adjustments
    adjustments = 0.0
    adj_match = re.search(r"Adjustments\s+£([\d,]+\.\d{2})", text)
    if adj_match:
        adjustments = float(adj_match.group(1).replace(",", ""))

    # Tips
    tips = 0.0
    tips_match = re.search(r"Tips\s+£([\d,]+\.\d{2})", text)
    if tips_match:
        tips = float(tips_match.group(1).replace(",", ""))

    # Grand total: "Total fee payable: £7.90"
    grand_total_match = re.search(r"Total fee payable:\s*£([\d,]+\.\d{2})", text)
    if not grand_total_match:
        raise ValueError("Could not find total fee payable")
    grand_total = float(grand_total_match.group(1).replace(",", ""))

    return Invoice(
        serial_number=serial_number,
        period_start=period_start,
        period_end=period_end,
        invoice_date=invoice_date,
        deliveries=deliveries,
        deliveries_total=deliveries_total,
        adjustments=adjustments,
        tips=tips,
        grand_total=grand_total,
    )


def parse_pdf(pdf_path: str | Path) -> Invoice:
    """High-level function: open PDF, extract text, parse into Invoice."""
    text = extract_text(pdf_path)
    return parse_invoice(text)
