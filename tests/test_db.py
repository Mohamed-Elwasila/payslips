"""Tests for the database layer."""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db import (
    Base, InvoiceModel, DeliveryModel, save_invoice, invoice_exists,
    get_invoices_by_tax_year, get_invoices_by_year, get_summary,
    get_summary_by_tax_year, get_tax_year_total,
)
from src.parser import Invoice, Delivery


def _get_test_session():
    """Create an in-memory SQLite database for testing (no PostgreSQL needed)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _sample_invoice():
    """Create a sample Invoice dataclass for testing."""
    return Invoice(
        serial_number="ri_gb_test_001",
        period_start=date(2026, 2, 17),
        period_end=date(2026, 2, 21),
        invoice_date=date(2026, 2, 24),
        deliveries=[
            Delivery(day="Tuesday", date=date(2026, 2, 17), orders_delivered=1, total=4.51),
            Delivery(day="Saturday", date=date(2026, 2, 21), orders_delivered=1, total=3.39),
        ],
        deliveries_total=7.90,
        adjustments=0.0,
        tips=0.0,
        grand_total=7.90,
    )


def test_save_invoice():
    session = _get_test_session()
    invoice = _sample_invoice()

    result = save_invoice(session, invoice)
    assert result is True

    db_invoice = session.query(InvoiceModel).first()
    assert db_invoice.serial_number == "ri_gb_test_001"
    assert db_invoice.grand_total == 7.90
    assert len(db_invoice.deliveries) == 2


def test_save_duplicate_is_skipped():
    session = _get_test_session()
    invoice = _sample_invoice()

    save_invoice(session, invoice)
    result = save_invoice(session, invoice)
    assert result is False

    count = session.query(InvoiceModel).count()
    assert count == 1


def test_invoice_exists():
    session = _get_test_session()
    invoice = _sample_invoice()

    assert invoice_exists(session, "ri_gb_test_001") is False
    save_invoice(session, invoice)
    assert invoice_exists(session, "ri_gb_test_001") is True


def test_delivery_foreign_key():
    session = _get_test_session()
    invoice = _sample_invoice()
    save_invoice(session, invoice)

    delivery = session.query(DeliveryModel).first()
    assert delivery.invoice.serial_number == "ri_gb_test_001"
    assert delivery.day == "Tuesday"
    assert delivery.total == 4.51


def test_get_summary():
    session = _get_test_session()
    save_invoice(session, _sample_invoice())

    rows = get_summary(session)
    assert len(rows) == 1
    assert rows[0]["year"] == 2026
    assert rows[0]["month"] == 2
    assert rows[0]["total_earned"] == 7.90
    assert rows[0]["invoice_count"] == 1


def test_get_summary_filters_by_year():
    session = _get_test_session()
    save_invoice(session, _sample_invoice())

    rows = get_summary(session, year=2025)
    assert len(rows) == 0

    rows = get_summary(session, year=2026)
    assert len(rows) == 1


def _invoice_with_date(serial, invoice_date):
    """Create an invoice with a specific date for tax year testing."""
    return Invoice(
        serial_number=serial,
        period_start=invoice_date,
        period_end=invoice_date,
        invoice_date=invoice_date,
        deliveries=[
            Delivery(day="Monday", date=invoice_date, orders_delivered=1, total=10.00),
        ],
        deliveries_total=10.00,
        adjustments=0.0,
        tips=0.0,
        grand_total=10.00,
    )


def test_get_summary_by_tax_year():
    session = _get_test_session()

    # Invoice in tax year 2025/2026 (after 6 April 2025)
    save_invoice(session, _invoice_with_date("tax_1", date(2025, 5, 10)))
    # Invoice in tax year 2025/2026 (before 5 April 2026)
    save_invoice(session, _invoice_with_date("tax_2", date(2026, 3, 15)))
    # Invoice outside tax year 2025/2026 (after 5 April 2026)
    save_invoice(session, _invoice_with_date("tax_3", date(2026, 5, 1)))

    rows = get_summary_by_tax_year(session, 2025)
    assert len(rows) == 2
    assert rows[0]["year"] == 2025
    assert rows[0]["month"] == 5
    assert rows[1]["year"] == 2026
    assert rows[1]["month"] == 3


def test_get_summary_by_tax_year_empty():
    session = _get_test_session()
    save_invoice(session, _invoice_with_date("tax_4", date(2026, 5, 1)))

    rows = get_summary_by_tax_year(session, 2024)
    assert len(rows) == 0


def test_get_tax_year_total():
    session = _get_test_session()
    save_invoice(session, _invoice_with_date("tax_5", date(2025, 6, 1)))
    save_invoice(session, _invoice_with_date("tax_6", date(2026, 1, 15)))
    save_invoice(session, _invoice_with_date("tax_7", date(2026, 6, 1)))

    total = get_tax_year_total(session, 2025)
    assert total == 20.00


def test_tax_year_boundary_dates():
    session = _get_test_session()
    # 5 April = last day of tax year 2024/2025
    save_invoice(session, _invoice_with_date("boundary_1", date(2025, 4, 5)))
    # 6 April = first day of tax year 2025/2026
    save_invoice(session, _invoice_with_date("boundary_2", date(2025, 4, 6)))

    assert get_tax_year_total(session, 2024) == 10.00
    assert get_tax_year_total(session, 2025) == 10.00


def test_get_invoices_by_tax_year():
    session = _get_test_session()
    save_invoice(session, _invoice_with_date("tax_list_1", date(2025, 4, 6)))
    save_invoice(session, _invoice_with_date("tax_list_2", date(2026, 4, 5)))
    save_invoice(session, _invoice_with_date("tax_list_3", date(2026, 4, 6)))

    invoices = get_invoices_by_tax_year(session, 2025)

    assert len(invoices) == 2
    assert invoices[0]["serial_number"] == "tax_list_2"
    assert invoices[1]["serial_number"] == "tax_list_1"


def test_get_invoices_by_year():
    session = _get_test_session()
    save_invoice(session, _invoice_with_date("year_list_1", date(2025, 12, 1)))
    save_invoice(session, _invoice_with_date("year_list_2", date(2026, 1, 1)))
    save_invoice(session, _invoice_with_date("year_list_3", date(2025, 9, 1)))

    invoices = get_invoices_by_year(session, 2025)

    assert len(invoices) == 2
    assert invoices[0]["serial_number"] == "year_list_1"
    assert invoices[1]["serial_number"] == "year_list_3"
