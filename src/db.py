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
