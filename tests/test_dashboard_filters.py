"""Exercise rendered dashboard filters against an isolated SQLite database."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from src import db


@pytest.fixture
def dashboard_db(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard.db'}")
    db.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    with factory() as session:
        yield session
    engine.dispose()


def add_invoice(session, invoice_date):
    session.add(db.InvoiceModel(
        serial_number=invoice_date.isoformat(), period_start=invoice_date,
        period_end=invoice_date, invoice_date=invoice_date,
        deliveries_total=10.0, tips=0.0, adjustments=0.0, grand_total=10.0,
    ))
    session.commit()


def run_dashboard():
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "src" / "dashboard.py"),
        default_timeout=15,
    ).run()
    if app.exception:
        pytest.fail(str(app.exception))
    return app


def test_empty_dashboard_renders_zero_totals(dashboard_db):
    app = run_dashboard()
    assert [metric.value for metric in app.metric][:3] == ["£0.00"] * 3


@pytest.mark.parametrize("day", [5, 6])
def test_april_boundary_is_available_in_tax_year_filter(dashboard_db, day):
    add_invoice(dashboard_db, date(2026, 4, day))
    app = run_dashboard()
    app.sidebar.radio[0].set_value("Tax Year").run()
    if app.exception:
        pytest.fail(str(app.exception))
    options = app.sidebar.selectbox[0].options
    expected = "2025/2026" if day == 5 else "2026/2027"
    assert expected in options
    app.sidebar.selectbox[0].select(expected).run()
    assert not app.exception
    assert app.metric[0].value == "£10.00"


def test_expense_only_year_is_selectable(dashboard_db):
    add_invoice(dashboard_db, date(2026, 2, 1))
    db.save_expense(
        dashboard_db, expense_date=date(2025, 8, 1), supplier="Test supplier",
        description="Test expense", category="equipment", amount=20.0,
    )
    app = run_dashboard()
    assert "2025" in app.sidebar.selectbox[0].options
    app.sidebar.selectbox[0].select("2025").run()
    assert not app.exception
    assert app.metric[1].value == "£20.00"
