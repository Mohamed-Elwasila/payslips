"""Tests for the Deliveroo invoice parser."""

from datetime import date

from src.parser import Delivery, Invoice, parse_invoice


# Sample text that mimics what pdfplumber extracts from a Deliveroo invoice
SAMPLE_TEXT = """Roofoods Limited
1 Cousin Lane
London
United Kingdom
EC4R 3TE
Company Number: 08167130
VAT Number: 286 7364 55
Name: Mohamed elmujtaba isam mohamed Elwasila
Address: Knole Lane, 17, BS10 6SD, Bristol, UK
Self-Billing Invoice
Services supplied: Food and Beverage Delivery
Invoice serial number: ri_gb_9e5e83cf-82df-469e-822f-f7e0a3caef9b_12
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
    assert invoice.serial_number == "ri_gb_9e5e83cf-82df-469e-822f-f7e0a3caef9b_12"


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
