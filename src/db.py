"""
Database models and connection setup using SQLAlchemy.

Tables:
- invoices: stores invoice metadata (serial number, dates, totals)
- deliveries: stores individual delivery rows, linked to an invoice
- expenses: stores expense records for profit/tax tracking
- expense_receipts: stores uploaded receipt metadata and file paths
"""

import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    func,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, selectinload

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


class ExpenseModel(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    expense_date = Column(Date, nullable=False)
    supplier = Column(String, nullable=False)
    description = Column(String, nullable=False)
    category = Column(String, nullable=False)
    payment_method = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    amount = Column(Float, nullable=False)
    business_use_percent = Column(Float, nullable=False, default=100.0)
    allowable_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    receipts = relationship(
        "ExpenseReceiptModel",
        back_populates="expense",
        cascade="all, delete-orphan",
    )


class ExpenseReceiptModel(Base):
    __tablename__ = "expense_receipts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    expense_id = Column(Integer, ForeignKey("expenses.id"), nullable=False)
    original_filename = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, nullable=False, server_default=func.now())

    expense = relationship("ExpenseModel", back_populates="receipts")


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


def save_expense(
    session,
    *,
    expense_date,
    supplier: str,
    description: str,
    category: str,
    amount: float,
    business_use_percent: float = 100.0,
    payment_method: str | None = None,
    notes: str | None = None,
    receipts: list[dict] | None = None,
):
    """Save an expense record and its receipt metadata."""
    allowable_amount = round(amount * (business_use_percent / 100.0), 2)
    expense = ExpenseModel(
        expense_date=expense_date,
        supplier=supplier.strip(),
        description=description.strip(),
        category=category,
        payment_method=payment_method.strip() if payment_method else None,
        notes=notes.strip() if notes else None,
        amount=amount,
        business_use_percent=business_use_percent,
        allowable_amount=allowable_amount,
    )
    session.add(expense)
    session.flush()

    for receipt in receipts or []:
        session.add(
            ExpenseReceiptModel(
                expense_id=expense.id,
                original_filename=receipt["original_filename"],
                stored_path=receipt["stored_path"],
                mime_type=receipt.get("mime_type"),
                file_size=receipt.get("file_size"),
            )
        )

    session.commit()
    session.refresh(expense)
    return expense


def store_receipt_file(
    uploaded_file,
    expense_date,
    storage_root: str | Path = "data/receipts",
) -> dict:
    """Persist an uploaded receipt file and return its stored metadata."""
    root = Path(storage_root)
    suffix = Path(uploaded_file.name).suffix.lower()
    subdir = root / str(expense_date.year) / f"{expense_date.month:02d}"
    subdir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}{suffix}"
    stored_path = subdir / stored_name
    stored_path.write_bytes(uploaded_file.getbuffer())
    return {
        "original_filename": uploaded_file.name,
        "stored_path": str(stored_path),
        "mime_type": getattr(uploaded_file, "type", None),
        "file_size": getattr(uploaded_file, "size", None),
    }


def get_summary(session, year: int = None):
    """
    Get earnings summary grouped by month.

    Returns a list of dicts with: year, month, invoice_count, total_earned.
    If year is provided, filter to that year only.
    """
    from sqlalchemy import extract

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
    from sqlalchemy import extract

    result = session.query(
        func.sum(InvoiceModel.grand_total)
    ).filter(
        extract("year", InvoiceModel.invoice_date) == year
    ).scalar()

    return float(result) if result else 0.0


def get_latest_invoice_date(session):
    """Return the newest invoice date saved in the database, if any."""
    return session.query(func.max(InvoiceModel.invoice_date)).scalar()


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
    from sqlalchemy import extract

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


def get_expenses(session):
    """Get all expenses ordered by date (newest first)."""
    expenses = (
        session.query(ExpenseModel)
        .options(selectinload(ExpenseModel.receipts))
        .order_by(ExpenseModel.expense_date.desc(), ExpenseModel.id.desc())
        .all()
    )
    return [_expense_to_dict(expense) for expense in expenses]


def get_expenses_by_year(session, year: int):
    """Get expenses for a calendar year ordered by date (newest first)."""
    from sqlalchemy import extract

    expenses = (
        session.query(ExpenseModel)
        .options(selectinload(ExpenseModel.receipts))
        .filter(extract("year", ExpenseModel.expense_date) == year)
        .order_by(ExpenseModel.expense_date.desc(), ExpenseModel.id.desc())
        .all()
    )
    return [_expense_to_dict(expense) for expense in expenses]


def get_expenses_by_tax_year(session, start_year: int):
    """Get expenses for a UK tax year ordered by date (newest first)."""
    tax_start, tax_end = _tax_year_dates(start_year)
    expenses = (
        session.query(ExpenseModel)
        .options(selectinload(ExpenseModel.receipts))
        .filter(
            ExpenseModel.expense_date >= tax_start,
            ExpenseModel.expense_date <= tax_end,
        )
        .order_by(ExpenseModel.expense_date.desc(), ExpenseModel.id.desc())
        .all()
    )
    return [_expense_to_dict(expense) for expense in expenses]


def get_expense_total(session, year: int | None = None) -> float:
    """Get allowable expense total for all time or a calendar year."""
    from sqlalchemy import extract

    query = session.query(func.sum(ExpenseModel.allowable_amount))
    if year is not None:
        query = query.filter(extract("year", ExpenseModel.expense_date) == year)
    result = query.scalar()
    return float(result) if result else 0.0


def get_tax_year_expense_total(session, start_year: int) -> float:
    """Get allowable expense total for a UK tax year."""
    tax_start, tax_end = _tax_year_dates(start_year)
    result = (
        session.query(func.sum(ExpenseModel.allowable_amount))
        .filter(
            ExpenseModel.expense_date >= tax_start,
            ExpenseModel.expense_date <= tax_end,
        )
        .scalar()
    )
    return float(result) if result else 0.0


def get_expense_summary(session, year: int | None = None):
    """Get allowable expenses grouped by month for all time or a calendar year."""
    from sqlalchemy import extract

    query = (
        session.query(
            extract("year", ExpenseModel.expense_date).label("year"),
            extract("month", ExpenseModel.expense_date).label("month"),
            func.count(ExpenseModel.id).label("expense_count"),
            func.sum(ExpenseModel.allowable_amount).label("total_spent"),
        )
        .group_by(
            extract("year", ExpenseModel.expense_date),
            extract("month", ExpenseModel.expense_date),
        )
        .order_by(
            extract("year", ExpenseModel.expense_date),
            extract("month", ExpenseModel.expense_date),
        )
    )
    if year is not None:
        query = query.filter(extract("year", ExpenseModel.expense_date) == year)
    return [
        {
            "year": int(row.year),
            "month": int(row.month),
            "expense_count": row.expense_count,
            "total_spent": float(row.total_spent),
        }
        for row in query.all()
    ]


def get_expense_summary_by_tax_year(session, start_year: int):
    """Get allowable expenses grouped by month for a UK tax year."""
    from sqlalchemy import extract

    tax_start, tax_end = _tax_year_dates(start_year)
    query = (
        session.query(
            extract("year", ExpenseModel.expense_date).label("year"),
            extract("month", ExpenseModel.expense_date).label("month"),
            func.count(ExpenseModel.id).label("expense_count"),
            func.sum(ExpenseModel.allowable_amount).label("total_spent"),
        )
        .filter(
            ExpenseModel.expense_date >= tax_start,
            ExpenseModel.expense_date <= tax_end,
        )
        .group_by(
            extract("year", ExpenseModel.expense_date),
            extract("month", ExpenseModel.expense_date),
        )
        .order_by(
            extract("year", ExpenseModel.expense_date),
            extract("month", ExpenseModel.expense_date),
        )
    )
    return [
        {
            "year": int(row.year),
            "month": int(row.month),
            "expense_count": row.expense_count,
            "total_spent": float(row.total_spent),
        }
        for row in query.all()
    ]


def get_expense_category_summary(session, year: int | None = None):
    """Get allowable expenses grouped by category for all time or a calendar year."""
    from sqlalchemy import extract

    query = (
        session.query(
            ExpenseModel.category.label("category"),
            func.count(ExpenseModel.id).label("expense_count"),
            func.sum(ExpenseModel.allowable_amount).label("total_spent"),
        )
        .group_by(ExpenseModel.category)
        .order_by(func.sum(ExpenseModel.allowable_amount).desc())
    )
    if year is not None:
        query = query.filter(extract("year", ExpenseModel.expense_date) == year)
    return [
        {
            "category": row.category,
            "expense_count": row.expense_count,
            "total_spent": float(row.total_spent),
        }
        for row in query.all()
    ]


def get_expense_category_summary_by_tax_year(session, start_year: int):
    """Get allowable expenses grouped by category for a UK tax year."""
    tax_start, tax_end = _tax_year_dates(start_year)
    query = (
        session.query(
            ExpenseModel.category.label("category"),
            func.count(ExpenseModel.id).label("expense_count"),
            func.sum(ExpenseModel.allowable_amount).label("total_spent"),
        )
        .filter(
            ExpenseModel.expense_date >= tax_start,
            ExpenseModel.expense_date <= tax_end,
        )
        .group_by(ExpenseModel.category)
        .order_by(func.sum(ExpenseModel.allowable_amount).desc())
    )
    return [
        {
            "category": row.category,
            "expense_count": row.expense_count,
            "total_spent": float(row.total_spent),
        }
        for row in query.all()
    ]


def _expense_to_dict(expense: ExpenseModel):
    """Convert an expense ORM object to a dict."""
    return {
        "id": expense.id,
        "expense_date": expense.expense_date,
        "supplier": expense.supplier,
        "description": expense.description,
        "category": expense.category,
        "payment_method": expense.payment_method,
        "notes": expense.notes,
        "amount": expense.amount,
        "business_use_percent": expense.business_use_percent,
        "allowable_amount": expense.allowable_amount,
        "receipts": [
            {
                "original_filename": receipt.original_filename,
                "stored_path": receipt.stored_path,
                "mime_type": receipt.mime_type,
                "file_size": receipt.file_size,
            }
            for receipt in expense.receipts
        ],
    }
