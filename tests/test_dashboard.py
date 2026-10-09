"""Tests for the pure data-shaping helpers in src.dashboard.

src/dashboard.py has no ``if __name__ == "__main__":`` guard: the whole
Streamlit script (sidebar widgets, forms, tabs, init_db()/get_session()
against Postgres) runs the moment the module is imported. A plain
``import src.dashboard`` therefore either needs a live Postgres server, or
-- if the DB is swapped for SQLite -- actually executes the real
st.form()/st.button() widget tree, which leaves Streamlit's internal
script-run bookkeeping in a state that breaks other tests in the same
process (observed: it makes tests/test_dashboard_filters.py's AppTest runs
fail with "st.button() can't be used in an st.form()" even though that
button is not inside a form).

To exercise the pure helper functions in isolation, without running any
Streamlit/DB code at all, we parse src/dashboard.py with ``ast`` and exec
only the handful of self-contained function definitions we need, inside a
throwaway namespace. None of these functions touch ``st`` or the database.
"""

import ast
from datetime import date, timedelta
from pathlib import Path

import pytest

DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "src" / "dashboard.py"
PURE_FUNCTIONS = {
    "get_tax_week",
    "get_invoice_tax_year",
    "format_month_label",
    "build_invoice_display_df",
    "build_expense_display_df",
    "build_profit_chart",
}


@pytest.fixture(scope="module")
def dashboard():
    import altair as alt
    import pandas as pd

    from src.db import _tax_year_dates

    source = DASHBOARD_PATH.read_text()
    tree = ast.parse(source)
    nodes = [
        node for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in PURE_FUNCTIONS)
        or (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "MONTH_NAMES" for t in node.targets)
        )
    ]
    assert {n.name for n in nodes if isinstance(n, ast.FunctionDef)} == PURE_FUNCTIONS

    module_ast = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module_ast)
    code = compile(module_ast, filename=str(DASHBOARD_PATH), mode="exec")

    namespace = {"date": date, "pd": pd, "alt": alt, "_tax_year_dates": _tax_year_dates}
    exec(code, namespace)

    from types import SimpleNamespace
    return SimpleNamespace(**{name: namespace[name] for name in PURE_FUNCTIONS})


# --- get_tax_week ------------------------------------------------------

def test_get_tax_week_first_day_is_week_one(dashboard):
    tax_year_start = date(2025, 4, 6)
    assert dashboard.get_tax_week(tax_year_start, tax_year_start) == 1


def test_get_tax_week_last_day_of_week_one(dashboard):
    tax_year_start = date(2025, 4, 6)
    assert dashboard.get_tax_week(tax_year_start + timedelta(days=6), tax_year_start) == 1


def test_get_tax_week_first_day_of_week_two(dashboard):
    tax_year_start = date(2025, 4, 6)
    assert dashboard.get_tax_week(tax_year_start + timedelta(days=7), tax_year_start) == 2


def test_get_tax_week_last_day_of_tax_year_is_week_53(dashboard):
    # 2025/2026 tax year: 6 April 2025 to 5 April 2026 (365 days total).
    tax_year_start = date(2025, 4, 6)
    tax_year_end = date(2026, 4, 5)
    assert dashboard.get_tax_week(tax_year_end, tax_year_start) == 53


def test_get_tax_week_handles_calendar_year_rollover(dashboard):
    # A tax year starting in April spans into the next calendar year; the
    # week count must keep climbing smoothly across 31 December/1 January
    # rather than resetting just because the calendar year changed.
    tax_year_start = date(2025, 4, 6)
    dec_31 = dashboard.get_tax_week(date(2025, 12, 31), tax_year_start)
    jan_1 = dashboard.get_tax_week(date(2026, 1, 1), tax_year_start)
    assert dec_31 == 39
    assert jan_1 == 39


def test_get_tax_week_before_start_returns_none(dashboard):
    tax_year_start = date(2025, 4, 6)
    assert dashboard.get_tax_week(date(2025, 4, 5), tax_year_start) is None


# --- format_month_label --------------------------------------------------

@pytest.mark.parametrize("month, name", [
    (1, "January"), (2, "February"), (3, "March"), (4, "April"),
    (5, "May"), (6, "June"), (7, "July"), (8, "August"),
    (9, "September"), (10, "October"), (11, "November"), (12, "December"),
])
def test_format_month_label_all_months(dashboard, month, name):
    assert dashboard.format_month_label(2025, month) == f"{name} 2025"


def test_format_month_label_accepts_numeric_strings(dashboard):
    # Pandas groupby columns can surface as strings; int() coercion must work.
    assert dashboard.format_month_label("2025", "3") == "March 2025"


def test_format_month_label_accepts_floats(dashboard):
    # Values coming off a pandas Series (e.g. from extract("year", ...)) are
    # often floats; the function must coerce them with int() first.
    assert dashboard.format_month_label(2025.0, 3.0) == "March 2025"


# --- build_invoice_display_df -------------------------------------------

def _invoice(
    serial_number="ri_1",
    period_start=date(2025, 4, 1),
    period_end=date(2025, 4, 7),
    invoice_date=date(2025, 4, 10),
    deliveries_total=100.5,
    tips=10.25,
    adjustments=-2.0,
    grand_total=108.75,
):
    return {
        "serial_number": serial_number,
        "period_start": period_start,
        "period_end": period_end,
        "invoice_date": invoice_date,
        "deliveries_total": deliveries_total,
        "tips": tips,
        "adjustments": adjustments,
        "grand_total": grand_total,
    }


def test_build_invoice_display_df_single_invoice_formats_columns(dashboard):
    df = dashboard.build_invoice_display_df([_invoice()])

    assert len(df) == 1
    row = df.iloc[0]
    assert row["Period Start"] == "2025-04-01"
    assert row["Period End"] == "2025-04-07"
    assert row["Invoice Date"] == "2025-04-10"
    assert row["Deliveries"] == "£100.50"
    assert row["Tips"] == "£10.25"
    assert row["Adjustments"] == "£-2.00"
    assert row["Total"] == "£108.75"
    assert row["Tax Year"] == "2025/2026"
    assert row["Tax Week"] == "W1"


def test_build_invoice_display_df_multiple_invoices_preserves_order_and_rows(dashboard):
    invoices = [
        _invoice(serial_number="ri_1", invoice_date=date(2025, 4, 10), grand_total=10.0),
        _invoice(serial_number="ri_2", invoice_date=date(2025, 5, 1), grand_total=20.0),
        _invoice(serial_number="ri_3", invoice_date=date(2026, 1, 1), grand_total=30.0),
    ]

    df = dashboard.build_invoice_display_df(invoices)

    assert df["serial_number"].tolist() == ["ri_1", "ri_2", "ri_3"]
    assert df["Total"].tolist() == ["£10.00", "£20.00", "£30.00"]
    # The January invoice is still inside the 2025/2026 UK tax year.
    assert df["Tax Year"].tolist() == ["2025/2026", "2025/2026", "2025/2026"]


@pytest.mark.xfail(
    strict=True,
    raises=KeyError,
    reason="build_invoice_display_df lacks the empty-list guard that build_expense_display_df has, "
    "so pd.DataFrame([]) has no invoice_date column and .apply() raises KeyError",
)
def test_build_invoice_display_df_empty_list_returns_empty_dataframe(dashboard):
    df = dashboard.build_invoice_display_df([])

    assert df.empty


# --- build_expense_display_df -------------------------------------------

def _expense(
    expense_date=date(2025, 5, 1),
    supplier="Shell",
    description="Fuel",
    category="fuel",
    payment_method="card",
    notes="note",
    amount=50.0,
    business_use_percent=80.0,
    allowable_amount=40.0,
    receipts=None,
):
    return {
        "id": 1,
        "expense_date": expense_date,
        "supplier": supplier,
        "description": description,
        "category": category,
        "payment_method": payment_method,
        "notes": notes,
        "amount": amount,
        "business_use_percent": business_use_percent,
        "allowable_amount": allowable_amount,
        "receipts": receipts if receipts is not None else [],
    }


def test_build_expense_display_df_empty_list_returns_empty_dataframe(dashboard):
    df = dashboard.build_expense_display_df([])

    assert df.empty


def test_build_expense_display_df_single_expense_formats_columns(dashboard):
    df = dashboard.build_expense_display_df([_expense()])

    assert len(df) == 1
    row = df.iloc[0]
    assert row["Expense Date"] == "2025-05-01"
    assert row["Category"] == "fuel"
    assert row["Supplier"] == "Shell"
    assert row["Amount"] == "£50.00"
    assert row["Business Use %"] == "80%"
    assert row["Allowable"] == "£40.00"
    assert row["Receipts"] == "-"


def test_build_expense_display_df_joins_multiple_receipt_filenames(dashboard):
    receipts = [
        {"original_filename": "a.pdf", "stored_path": "x", "mime_type": "application/pdf", "file_size": 1},
        {"original_filename": "b.png", "stored_path": "y", "mime_type": "image/png", "file_size": 2},
    ]
    df = dashboard.build_expense_display_df([_expense(receipts=receipts)])

    assert df.iloc[0]["Receipts"] == "a.pdf, b.png"


def test_build_expense_display_df_multiple_expenses_preserves_order(dashboard):
    expenses = [
        _expense(supplier="Shell", amount=10.0, allowable_amount=10.0),
        _expense(supplier="Halfords", amount=20.0, allowable_amount=15.0, business_use_percent=75.0),
    ]
    df = dashboard.build_expense_display_df(expenses)

    assert df["Supplier"].tolist() == ["Shell", "Halfords"]
    assert df["Amount"].tolist() == ["£10.00", "£20.00"]
    assert df["Business Use %"].tolist() == ["80%", "75%"]


# --- build_profit_chart --------------------------------------------------

def test_build_profit_chart_empty_inputs_returns_none(dashboard):
    assert dashboard.build_profit_chart([], []) is None


def test_build_profit_chart_single_data_point(dashboard):
    income = [{"year": 2025, "month": 4, "invoice_count": 1, "total_earned": 100.0}]

    chart = dashboard.build_profit_chart(income, [])

    assert chart is not None
    data = chart.data
    assert set(data["month_label"]) == {"April 2025"}
    income_amount = data.loc[data["series"] == "income", "amount"].iloc[0]
    expenses_amount = data.loc[data["series"] == "expenses", "amount"].iloc[0]
    profit_amount = data.loc[data["series"] == "profit", "amount"].iloc[0]
    assert income_amount == 100.0
    assert expenses_amount == 0.0
    assert profit_amount == 100.0


def test_build_profit_chart_mismatched_years_keeps_rows_independent(dashboard):
    # Income exists only for 2025, expenses only for 2026: both months must
    # appear, each with a zeroed-out counterpart series rather than being
    # dropped or merged together.
    income = [{"year": 2025, "month": 4, "invoice_count": 1, "total_earned": 100.0}]
    expense = [{"year": 2026, "month": 1, "expense_count": 1, "total_spent": 50.0}]

    chart = dashboard.build_profit_chart(income, expense)
    data = chart.data

    assert set(data["month_label"]) == {"April 2025", "January 2026"}
    april_income = data.loc[(data["month_label"] == "April 2025") & (data["series"] == "income"), "amount"].iloc[0]
    april_expenses = data.loc[(data["month_label"] == "April 2025") & (data["series"] == "expenses"), "amount"].iloc[0]
    jan_income = data.loc[(data["month_label"] == "January 2026") & (data["series"] == "income"), "amount"].iloc[0]
    jan_expenses = data.loc[(data["month_label"] == "January 2026") & (data["series"] == "expenses"), "amount"].iloc[0]
    jan_profit = data.loc[(data["month_label"] == "January 2026") & (data["series"] == "profit"), "amount"].iloc[0]
    assert april_income == 100.0
    assert april_expenses == 0.0
    assert jan_income == 0.0
    assert jan_expenses == 50.0
    assert jan_profit == -50.0

    # The x-axis sort order must follow chronological (year, month) order,
    # not the order rows happened to be supplied in. Altair's attribute
    # access on "sort" returns a property-setter helper, not the stored
    # value, so we read the resolved spec via to_dict() instead.
    chart_spec = chart.to_dict()
    assert chart_spec["encoding"]["x"]["sort"] == ["April 2025", "January 2026"]


def test_build_profit_chart_same_month_merges_income_and_expenses(dashboard):
    income = [{"year": 2025, "month": 6, "invoice_count": 2, "total_earned": 300.0}]
    expense = [{"year": 2025, "month": 6, "expense_count": 1, "total_spent": 120.0}]

    chart = dashboard.build_profit_chart(income, expense)
    data = chart.data

    assert len(data) == 3  # one month, three series
    profit = data.loc[data["series"] == "profit", "amount"].iloc[0]
    assert profit == 180.0


def test_build_profit_chart_encoding_and_mark_structure(dashboard):
    income = [{"year": 2025, "month": 4, "invoice_count": 1, "total_earned": 100.0}]

    chart = dashboard.build_profit_chart(income, [])
    chart_spec = chart.to_dict()

    assert chart_spec["mark"]["type"] == "line"
    assert chart_spec["mark"]["point"] is True
    assert chart_spec["encoding"]["x"]["field"] == "month_label"
    assert chart_spec["encoding"]["color"]["scale"]["domain"] == ["income", "expenses", "profit"]
    assert chart_spec["height"] == 200
