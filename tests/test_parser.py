"""Tests for the Deliveroo invoice parser."""

from datetime import date

import pytest

from src.parser import Delivery, Invoice, parse_invoice


# Sample text that mimics what pdfplumber extracts from a Deliveroo invoice
SAMPLE_TEXT = """Roofoods Limited
1 Cousin Lane
London
United Kingdom
EC4R 3TE
Company Number: 08167130
VAT Number: 286 7364 55
Name: Jordan Alex Taylor
Address: Example Road, 10, AB1 2CD, Sampleton, UK
Self-Billing Invoice
Services supplied: Food and Beverage Delivery
Invoice serial number: ri_gb_00000000-1111-2222-3333-444444444444_01
Invoice period: 17 February 2026 - 21 February 2026
Invoice Date: 24 February 2026
Deliveries
Day Date Orders Delivered Total
Tuesday 17 February 2026 1 £4.51
Saturday 21 February 2026 1 £3.39
Total 2 £7.90
Invoice Total
Item totals Total Gross
Deliveries £7.90 £7.90
Adjustments -- --
Tips -- --
Total £7.90 £7.90
Total fee payable: £7.90
"""


def test_parse_serial_number():
    invoice = parse_invoice(SAMPLE_TEXT)
    assert invoice.serial_number == "ri_gb_00000000-1111-2222-3333-444444444444_01"


def test_parse_period():
    invoice = parse_invoice(SAMPLE_TEXT)
    assert invoice.period_start == date(2026, 2, 17)
    assert invoice.period_end == date(2026, 2, 21)


def test_parse_invoice_date():
    invoice = parse_invoice(SAMPLE_TEXT)
    assert invoice.invoice_date == date(2026, 2, 24)


def test_parse_deliveries():
    invoice = parse_invoice(SAMPLE_TEXT)
    assert len(invoice.deliveries) == 2

    assert invoice.deliveries[0] == Delivery(
        day="Tuesday",
        date=date(2026, 2, 17),
        orders_delivered=1,
        total=4.51,
    )
    assert invoice.deliveries[1] == Delivery(
        day="Saturday",
        date=date(2026, 2, 21),
        orders_delivered=1,
        total=3.39,
    )


def test_parse_totals():
    invoice = parse_invoice(SAMPLE_TEXT)
    assert invoice.deliveries_total == 7.90
    assert invoice.adjustments == 0.0
    assert invoice.tips == 0.0
    assert invoice.grand_total == 7.90


def test_parse_with_tips_and_adjustments():
    """Test parsing when tips and adjustments have actual values."""
    text_with_extras = SAMPLE_TEXT.replace(
        "Adjustments -- --", "Adjustments £2.00 £2.00"
    ).replace(
        "Tips -- --", "Tips £5.50 £5.50"
    ).replace(
        "Total fee payable: £7.90", "Total fee payable: £15.40"
    )
    invoice = parse_invoice(text_with_extras)
    assert invoice.adjustments == 2.00
    assert invoice.tips == 5.50
    assert invoice.grand_total == 15.40


def test_parse_multiple_orders_per_day():
    """Test that a delivery row with multiple orders parses correctly."""
    text = SAMPLE_TEXT.replace(
        "Tuesday 17 February 2026 1 £4.51",
        "Tuesday 17 February 2026 5 £22.75",
    )
    invoice = parse_invoice(text)
    assert invoice.deliveries[0].orders_delivered == 5
    assert invoice.deliveries[0].total == 22.75


@pytest.mark.parametrize(
    "prefix, message",
    [
        ("Invoice serial number:", "Could not find invoice serial number"),
        ("Invoice period:", "Could not find invoice period"),
        ("Invoice Date:", "Could not find invoice date"),
        ("Total fee payable:", "Could not find total fee payable"),
    ],
)
def test_missing_required_field_is_rejected(prefix, message):
    text = "\n".join(
        line for line in SAMPLE_TEXT.splitlines() if not line.startswith(prefix)
    )

    with pytest.raises(ValueError, match=message):
        parse_invoice(text)


@pytest.mark.parametrize("text", ["", "   \n", "Unrelated document"])
def test_non_invoice_text_is_rejected(text):
    with pytest.raises(ValueError, match="Could not find invoice serial number"):
        parse_invoice(text)


def test_impossible_invoice_date_is_rejected():
    text = SAMPLE_TEXT.replace("Invoice Date: 24 February 2026", "Invoice Date: 30 February 2026")

    with pytest.raises(ValueError):
        parse_invoice(text)


def test_thousands_separators_in_amounts():
    text = SAMPLE_TEXT.replace("£4.51", "£1,004.51").replace("£7.90", "£1,007.90")

    invoice = parse_invoice(text)

    assert invoice.deliveries[0].total == 1004.51
    assert invoice.deliveries_total == 1007.90
    assert invoice.grand_total == 1007.90


@pytest.mark.parametrize("amount", ["-£2.00", "£-2.00"])
def test_negative_adjustments_preserve_sign(amount):
    text = SAMPLE_TEXT.replace(
        "Adjustments -- --", f"Adjustments {amount} {amount}"
    ).replace("Total £7.90 £7.90", "Total £5.90 £5.90").replace(
        "Total fee payable: £7.90", "Total fee payable: £5.90"
    )

    invoice = parse_invoice(text)

    assert invoice.adjustments == -2.0
    assert invoice.grand_total == 5.90


def test_missing_deliveries_subtotal_is_rejected():
    text = SAMPLE_TEXT.replace("Deliveries £7.90 £7.90\n", "")

    with pytest.raises(ValueError):
        parse_invoice(text)


def test_reversed_invoice_period_is_rejected():
    text = SAMPLE_TEXT.replace(
        "Invoice period: 17 February 2026 - 21 February 2026",
        "Invoice period: 21 February 2026 - 17 February 2026",
    )

    with pytest.raises(ValueError):
        parse_invoice(text)
