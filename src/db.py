"""
Database models and connection setup using SQLAlchemy.

Tables:
- invoices: stores invoice metadata (serial number, dates, totals)
- deliveries: stores individual delivery rows, linked to an invoice
"""

import os

from dotenv import load_dotenv
from sqlalchemy import (
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://payslips:payslips_dev@localhost:5432/payslips",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class InvoiceModel(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    serial_number = Column(String, unique=True, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    invoice_date = Column(Date, nullable=False)
    deliveries_total = Column(Float, default=0.0)
    adjustments = Column(Float, default=0.0)
    tips = Column(Float, default=0.0)
    grand_total = Column(Float, nullable=False)

    deliveries = relationship("DeliveryModel", back_populates="invoice")


class DeliveryModel(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    day = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    orders_delivered = Column(Integer, nullable=False)
    total = Column(Float, nullable=False)

    invoice = relationship("InvoiceModel", back_populates="deliveries")


def init_db():
    """Create all tables in the database."""
    Base.metadata.create_all(engine)


def get_session():
    """Get a new database session."""
    return SessionLocal()


def invoice_exists(session, serial_number: str) -> bool:
    """Check if an invoice with this serial number is already in the DB."""
    return (
        session.query(InvoiceModel)
        .filter(InvoiceModel.serial_number == serial_number)
        .first()
        is not None
    )


def save_invoice(session, invoice) -> bool:
    """
    Save a parsed Invoice object to the database.

    Returns True if saved, False if it already exists (duplicate).
    The 'invoice' parameter is a parser.Invoice dataclass instance.
    """
    if invoice_exists(session, invoice.serial_number):
        return False

    db_invoice = InvoiceModel(
        serial_number=invoice.serial_number,
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        invoice_date=invoice.invoice_date,
        deliveries_total=invoice.deliveries_total,
        adjustments=invoice.adjustments,
        tips=invoice.tips,
        grand_total=invoice.grand_total,
    )
    session.add(db_invoice)
    session.flush()  # get the auto-generated id

    for delivery in invoice.deliveries:
        db_delivery = DeliveryModel(
            invoice_id=db_invoice.id,
            day=delivery.day,
            date=delivery.date,
            orders_delivered=delivery.orders_delivered,
            total=delivery.total,
        )
        session.add(db_delivery)

    session.commit()
    return True


def get_summary(session, year: int = None):
    """
    Get earnings summary grouped by month.

    Returns a list of dicts with: year, month, invoice_count, total_earned.
    If year is provided, filter to that year only.
    """
    from sqlalchemy import func, extract

    query = session.query(
        extract("year", InvoiceModel.invoice_date).label("year"),
        extract("month", InvoiceModel.invoice_date).label("month"),
        func.count(InvoiceModel.id).label("invoice_count"),
        func.sum(InvoiceModel.grand_total).label("total_earned"),
    ).group_by(
        extract("year", InvoiceModel.invoice_date),
        extract("month", InvoiceModel.invoice_date),
    ).order_by(
        extract("year", InvoiceModel.invoice_date),
        extract("month", InvoiceModel.invoice_date),
    )

    if year:
        query = query.filter(
            extract("year", InvoiceModel.invoice_date) == year
        )

    results = []
    for row in query.all():
        results.append({
            "year": int(row.year),
            "month": int(row.month),
            "invoice_count": row.invoice_count,
            "total_earned": float(row.total_earned),
        })
    return results


def get_yearly_total(session, year: int) -> float:
    """Get total earnings for a specific year."""
    from sqlalchemy import func, extract

    result = session.query(
        func.sum(InvoiceModel.grand_total)
    ).filter(
        extract("year", InvoiceModel.invoice_date) == year
    ).scalar()

    return float(result) if result else 0.0


def _tax_year_dates(start_year: int):
    """Return (start_date, end_date) for UK tax year starting in April.

    Tax year 2025/2026 = 6 April 2025 to 5 April 2026.
    """
    from datetime import date
    return date(start_year, 4, 6), date(start_year + 1, 4, 5)


def get_summary_by_tax_year(session, start_year: int):
    """Get earnings summary grouped by month for a UK tax year.

    Tax year 2025/2026: pass start_year=2025.
    Returns list of dicts with: year, month, invoice_count, total_earned.
    """
    from sqlalchemy import func, extract

    tax_start, tax_end = _tax_year_dates(start_year)

    query = session.query(
        extract("year", InvoiceModel.invoice_date).label("year"),
        extract("month", InvoiceModel.invoice_date).label("month"),
        func.count(InvoiceModel.id).label("invoice_count"),
        func.sum(InvoiceModel.grand_total).label("total_earned"),
    ).filter(
        InvoiceModel.invoice_date >= tax_start,
        InvoiceModel.invoice_date <= tax_end,
    ).group_by(
        extract("year", InvoiceModel.invoice_date),
        extract("month", InvoiceModel.invoice_date),
    ).order_by(
        extract("year", InvoiceModel.invoice_date),
        extract("month", InvoiceModel.invoice_date),
    )

    results = []
    for row in query.all():
        results.append({
            "year": int(row.year),
            "month": int(row.month),
            "invoice_count": row.invoice_count,
            "total_earned": float(row.total_earned),
        })
    return results


def get_tax_year_total(session, start_year: int) -> float:
    """Get total earnings for a UK tax year."""
    from sqlalchemy import func

    tax_start, tax_end = _tax_year_dates(start_year)

    result = session.query(
        func.sum(InvoiceModel.grand_total)
    ).filter(
        InvoiceModel.invoice_date >= tax_start,
        InvoiceModel.invoice_date <= tax_end,
    ).scalar()

    return float(result) if result else 0.0


def get_all_invoices(session):
    """Get all invoices ordered by date (newest first)."""
    invoices = (
        session.query(InvoiceModel)
        .order_by(InvoiceModel.invoice_date.desc())
        .all()
    )
    return [
        {
            "serial_number": inv.serial_number,
            "period_start": inv.period_start,
            "period_end": inv.period_end,
            "invoice_date": inv.invoice_date,
            "deliveries_total": inv.deliveries_total,
            "tips": inv.tips,
            "adjustments": inv.adjustments,
            "grand_total": inv.grand_total,
        }
        for inv in invoices
    ]


def get_invoices_by_tax_year(session, start_year: int):
    """Get invoices for a UK tax year ordered by date (newest first)."""
    tax_start, tax_end = _tax_year_dates(start_year)
    invoices = (
        session.query(InvoiceModel)
        .filter(
            InvoiceModel.invoice_date >= tax_start,
            InvoiceModel.invoice_date <= tax_end,
        )
        .order_by(InvoiceModel.invoice_date.desc())
        .all()
    )
    return [
        {
            "serial_number": inv.serial_number,
            "period_start": inv.period_start,
            "period_end": inv.period_end,
            "invoice_date": inv.invoice_date,
            "deliveries_total": inv.deliveries_total,
            "tips": inv.tips,
            "adjustments": inv.adjustments,
            "grand_total": inv.grand_total,
        }
        for inv in invoices
    ]


def get_invoices_by_year(session, year: int):
    """Get invoices for a calendar year ordered by date (newest first)."""
    from sqlalchemy import extract

    invoices = (
        session.query(InvoiceModel)
        .filter(extract("year", InvoiceModel.invoice_date) == year)
        .order_by(InvoiceModel.invoice_date.desc())
        .all()
    )
    return [
        {
            "serial_number": inv.serial_number,
            "period_start": inv.period_start,
            "period_end": inv.period_end,
            "invoice_date": inv.invoice_date,
            "deliveries_total": inv.deliveries_total,
            "tips": inv.tips,
            "adjustments": inv.adjustments,
            "grand_total": inv.grand_total,
        }
        for inv in invoices
    ]
