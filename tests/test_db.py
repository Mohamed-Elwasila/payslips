"""Tests for the database layer."""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db import Base, InvoiceModel, DeliveryModel, save_invoice, invoice_exists, get_summary
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
