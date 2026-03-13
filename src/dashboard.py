"""Streamlit dashboard for Deliveroo earnings and expenses."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import altair as alt
import pandas as pd
import streamlit as st

from src.db import (
    _tax_year_dates,
    get_all_invoices,
    get_expense_category_summary,
    get_expense_category_summary_by_tax_year,
    get_expense_summary,
    get_expense_summary_by_tax_year,
    get_expense_total,
    get_expenses,
    get_expenses_by_tax_year,
    get_expenses_by_year,
    get_invoices_by_tax_year,
    get_invoices_by_year,
    get_session,
    get_summary,
    get_summary_by_tax_year,
    get_tax_year_expense_total,
    get_tax_year_total,
    get_yearly_total,
    init_db,
    save_expense,
    store_receipt_file,
)
from src.importer import import_uploaded_pdfs, summarize_results

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
EXPENSE_CATEGORIES = [
    "fuel",
    "maintenance",
    "parking",
    "insurance",
    "equipment",
    "phone",
    "food",
    "accounting",
    "other",
]
PAYMENT_METHODS = ["card", "cash", "bank transfer", "other"]


def get_tax_week(invoice_date, tax_year_start):
    """Calculate UK tax week number (Week 1 starts 6 April)."""
    delta = invoice_date - tax_year_start
    if delta.days < 0:
        return None
    return delta.days // 7 + 1


def get_invoice_tax_year(invoice_date):
    """Return UK tax year label and start date for an invoice date."""
    if invoice_date >= date(invoice_date.year, 4, 6):
        start_year = invoice_date.year
    else:
        start_year = invoice_date.year - 1
    tax_year_start, _ = _tax_year_dates(start_year)
    return f"{start_year}/{start_year + 1}", tax_year_start


def format_month_label(year, month):
    """Return a human-readable month label."""
    return f"{MONTH_NAMES[int(month)]} {int(year)}"


def build_invoice_display_df(invoices):
    """Prepare invoice rows for display."""
    inv_df = pd.DataFrame(invoices)
    inv_df["Tax Year"] = inv_df["invoice_date"].apply(
        lambda d: get_invoice_tax_year(d)[0]
    )
    inv_df["Tax Week"] = inv_df["invoice_date"].apply(
        lambda d: f"W{get_tax_week(d, get_invoice_tax_year(d)[1])}"
    )
    inv_df = inv_df.rename(columns={
        "period_start": "Period Start",
        "period_end": "Period End",
        "invoice_date": "Invoice Date",
        "deliveries_total": "Deliveries",
        "tips": "Tips",
        "adjustments": "Adjustments",
        "grand_total": "Total",
    })
    inv_df["Invoice Date"] = inv_df["Invoice Date"].astype(str)
    inv_df["Period Start"] = inv_df["Period Start"].astype(str)
    inv_df["Period End"] = inv_df["Period End"].astype(str)
    for col in ["Deliveries", "Tips", "Adjustments", "Total"]:
        inv_df[col] = inv_df[col].apply(lambda x: f"£{x:,.2f}")
    return inv_df


def build_expense_display_df(expenses):
    """Prepare expense rows for display."""
    if not expenses:
        return pd.DataFrame()

    exp_df = pd.DataFrame(expenses)
    exp_df = exp_df.rename(columns={
        "expense_date": "Expense Date",
        "supplier": "Supplier",
        "description": "Description",
        "category": "Category",
        "payment_method": "Payment Method",
        "notes": "Notes",
        "amount": "Amount",
        "business_use_percent": "Business Use %",
        "allowable_amount": "Allowable",
    })
    exp_df["Expense Date"] = exp_df["Expense Date"].astype(str)
    exp_df["Receipts"] = exp_df["receipts"].apply(
        lambda items: ", ".join(receipt["original_filename"] for receipt in items) if items else "-"
    )
    exp_df["Amount"] = exp_df["Amount"].apply(lambda x: f"£{x:,.2f}")
    exp_df["Allowable"] = exp_df["Allowable"].apply(lambda x: f"£{x:,.2f}")
    exp_df["Business Use %"] = exp_df["Business Use %"].apply(lambda x: f"{x:.0f}%")
    return exp_df[[
        "Expense Date",
        "Category",
        "Supplier",
        "Description",
        "Amount",
        "Business Use %",
        "Allowable",
        "Payment Method",
        "Receipts",
        "Notes",
    ]]


def build_profit_chart(income_rows, expense_rows):
    """Return a compact monthly income/expense/profit chart."""
    month_map = {}

    for row in income_rows:
        key = (int(row["year"]), int(row["month"]))
        month_map[key] = {
            "year": key[0],
            "month": key[1],
            "income": float(row["total_earned"]),
            "expenses": 0.0,
        }

    for row in expense_rows:
        key = (int(row["year"]), int(row["month"]))
        month_map.setdefault(
            key,
            {"year": key[0], "month": key[1], "income": 0.0, "expenses": 0.0},
        )
        month_map[key]["expenses"] = float(row["total_spent"])

    if not month_map:
        return None

    chart_df = pd.DataFrame(month_map.values()).sort_values(["year", "month"])
    chart_df["profit"] = chart_df["income"] - chart_df["expenses"]
    chart_df["month_label"] = chart_df.apply(
        lambda r: format_month_label(r["year"], r["month"]), axis=1
    )
    order = chart_df["month_label"].tolist()

    plot_df = chart_df.melt(
        id_vars=["month_label"],
        value_vars=["income", "expenses", "profit"],
        var_name="series",
        value_name="amount",
    )
    color_scale = alt.Scale(
        domain=["income", "expenses", "profit"],
        range=["#2F6DB4", "#C85C3E", "#2A7A4B"],
    )

    return (
        alt.Chart(plot_df)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X(
                "month_label:N",
                sort=order,
                axis=alt.Axis(labelAngle=0, title=None, labelLimit=140),
            ),
            y=alt.Y("amount:Q", title="Amount (£)"),
            color=alt.Color("series:N", scale=color_scale, title=""),
            tooltip=[
                alt.Tooltip("month_label:N", title="Month"),
                alt.Tooltip("series:N", title="Series"),
                alt.Tooltip("amount:Q", title="Amount", format=",.2f"),
            ],
        )
        .properties(height=200)
    )


def render_import_results():
    """Render the latest import run if present."""
    results = st.session_state.get("last_import_results", [])
    if not results:
        st.caption("No import run yet.")
        return

    summary = summarize_results(results)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Saved", summary["saved"])
    col2.metric("Duplicates", summary["duplicate"])
    col3.metric("Parse Errors", summary["error"])
    col4.metric("Invalid", summary["invalid"])

    table_df = pd.DataFrame([
        {
            "File": result.source_name,
            "Status": result.status.title(),
            "Invoice": result.serial_number or "-",
            "Total": f"£{result.total:,.2f}" if result.total is not None else "-",
            "Message": result.message,
        }
        for result in results
    ])
    st.dataframe(table_df, use_container_width=True, hide_index=True)


st.set_page_config(page_title="Deliveroo Earnings", layout="wide")
st.title("Deliveroo Earnings Dashboard")

init_db()
session = get_session()

try:
    st.sidebar.header("Filters")
    view_mode = st.sidebar.radio("View by", ["Calendar Year", "Tax Year"])

    st.sidebar.divider()
    st.sidebar.subheader("Import PDFs")
    uploaded_files = st.sidebar.file_uploader(
        "Upload Deliveroo invoice PDFs",
        type=["pdf"],
        accept_multiple_files=True,
    )
    if st.sidebar.button("Import uploads", width="stretch"):
        if uploaded_files:
            st.session_state["last_import_results"] = import_uploaded_pdfs(
                session,
                uploaded_files,
            )
            st.rerun()
        else:
            st.sidebar.caption("Choose one or more PDF files first.")

    all_summary = get_summary(session)
    income_rows = []
    expense_rows = []
    category_rows = []
    invoices = []
    expenses = []
    income_total = 0.0
    expense_total = 0.0
    total_label = "No data yet"

    if all_summary:
        available_years = sorted(set(r["year"] for r in all_summary))

        if view_mode == "Calendar Year":
            selected_year = st.sidebar.selectbox("Year", ["All"] + available_years)
            if selected_year == "All":
                income_rows = all_summary
                income_total = sum(r["total_earned"] for r in income_rows)
                expense_rows = get_expense_summary(session)
                expense_total = get_expense_total(session)
                category_rows = get_expense_category_summary(session)
                invoices = get_all_invoices(session)
                expenses = get_expenses(session)
                total_label = "All Time"
            else:
                income_rows = get_summary(session, year=selected_year)
                income_total = get_yearly_total(session, selected_year)
                expense_rows = get_expense_summary(session, selected_year)
                expense_total = get_expense_total(session, selected_year)
                category_rows = get_expense_category_summary(session, selected_year)
                invoices = get_invoices_by_year(session, selected_year)
                expenses = get_expenses_by_year(session, selected_year)
                total_label = str(selected_year)
        else:
            tax_years = sorted(
                set(y for y in range(min(available_years) - 1, max(available_years) + 1)),
                reverse=True,
            )
            tax_year_labels = [f"{y}/{y + 1}" for y in tax_years]
            selected_label = st.sidebar.selectbox("Tax Year", tax_year_labels)
            start_year = int(selected_label.split("/")[0])
            income_rows = get_summary_by_tax_year(session, start_year)
            income_total = get_tax_year_total(session, start_year)
            expense_rows = get_expense_summary_by_tax_year(session, start_year)
            expense_total = get_tax_year_expense_total(session, start_year)
            category_rows = get_expense_category_summary_by_tax_year(session, start_year)
            invoices = get_invoices_by_tax_year(session, start_year)
            expenses = get_expenses_by_tax_year(session, start_year)
            total_label = f"Tax Year {selected_label}"
    else:
        expenses = get_expenses(session)
        expense_rows = get_expense_summary(session)
        expense_total = get_expense_total(session)
        category_rows = get_expense_category_summary(session)

    overview_tab, invoices_tab, expenses_tab, imports_tab = st.tabs(
        ["Overview", "Invoices", "Expenses", "Imports"]
    )

    with overview_tab:
        profit_total = income_total - expense_total
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Income", f"£{income_total:,.2f}")
        col2.metric("Expenses", f"£{expense_total:,.2f}")
        col3.metric("Profit", f"£{profit_total:,.2f}")
        col4.metric("Period", total_label)

        st.subheader("Monthly Income vs Expenses", anchor=False)
        profit_chart = build_profit_chart(income_rows, expense_rows)
        if profit_chart is not None:
            st.altair_chart(profit_chart, use_container_width=True)
        else:
            st.caption("No monthly data for the selected period.")

        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Monthly Income", anchor=False)
            if income_rows:
                income_df = pd.DataFrame(income_rows)
                income_df["Month"] = income_df.apply(
                    lambda r: format_month_label(r["year"], r["month"]), axis=1
                )
                income_df = income_df.rename(columns={
                    "invoice_count": "Invoices",
                    "total_earned": "Earned",
                })
                income_df["Earned"] = income_df["Earned"].apply(lambda x: f"£{x:,.2f}")
                st.dataframe(
                    income_df[["Month", "Invoices", "Earned"]],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No income rows for the selected period.")

        with col_right:
            st.subheader("Monthly Expenses", anchor=False)
            if expense_rows:
                expense_df = pd.DataFrame(expense_rows)
                expense_df["Month"] = expense_df.apply(
                    lambda r: format_month_label(r["year"], r["month"]), axis=1
                )
                expense_df = expense_df.rename(columns={
                    "expense_count": "Expenses",
                    "total_spent": "Allowable",
                })
                expense_df["Allowable"] = expense_df["Allowable"].apply(lambda x: f"£{x:,.2f}")
                st.dataframe(
                    expense_df[["Month", "Expenses", "Allowable"]],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No expense rows for the selected period.")

        st.subheader("Expense Categories", anchor=False)
        if category_rows:
            category_df = pd.DataFrame(category_rows)
            category_df = category_df.rename(columns={
                "category": "Category",
                "expense_count": "Expenses",
                "total_spent": "Allowable",
            })
            category_df["Allowable"] = category_df["Allowable"].apply(lambda x: f"£{x:,.2f}")
            st.dataframe(category_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No expense categories yet.")

    with invoices_tab:
        st.subheader("Invoices", anchor=False)
        if invoices:
            invoice_df = build_invoice_display_df(invoices)
            display_df = invoice_df[[
                "Tax Year",
                "Tax Week",
                "Invoice Date",
                "Period Start",
                "Period End",
                "Deliveries",
                "Tips",
                "Adjustments",
                "Total",
            ]]
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No invoices for the selected period.")

    with expenses_tab:
        st.subheader("Add Expense", anchor=False)
        with st.form("expense_form", clear_on_submit=True):
            exp_col1, exp_col2, exp_col3 = st.columns(3)
            expense_date = exp_col1.date_input("Expense Date", value=date.today())
            category = exp_col2.selectbox("Category", EXPENSE_CATEGORIES)
            payment_method = exp_col3.selectbox("Payment Method", PAYMENT_METHODS)

            supplier = st.text_input("Supplier", placeholder="Shell, Halfords, Tesco...")
            description = st.text_input("Description", placeholder="Fuel, tyre repair, phone holder...")

            amt_col1, amt_col2 = st.columns(2)
            amount = amt_col1.number_input("Amount", min_value=0.0, step=0.01, format="%.2f")
            business_use_percent = amt_col2.number_input(
                "Business Use %",
                min_value=0.0,
                max_value=100.0,
                value=100.0,
                step=5.0,
                format="%.0f",
            )

            notes = st.text_area("Notes", placeholder="Optional details for tax records")
            receipt_files = st.file_uploader(
                "Receipts",
                type=["pdf", "png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                key="expense_receipts",
            )
            submitted = st.form_submit_button("Save expense", width="stretch")

            if submitted:
                if not supplier.strip() or not description.strip() or amount <= 0:
                    st.warning("Supplier, description, and a positive amount are required.")
                else:
                    stored_receipts = [
                        store_receipt_file(uploaded_file, expense_date)
                        for uploaded_file in (receipt_files or [])
                    ]
                    save_expense(
                        session,
                        expense_date=expense_date,
                        supplier=supplier,
                        description=description,
                        category=category,
                        amount=float(amount),
                        business_use_percent=float(business_use_percent),
                        payment_method=payment_method,
                        notes=notes,
                        receipts=stored_receipts,
                    )
                    st.session_state["expense_saved"] = True
                    st.rerun()

        if st.session_state.pop("expense_saved", False):
            st.success("Expense saved.")

        st.subheader("Expenses", anchor=False)
        expense_table_df = build_expense_display_df(expenses)
        if not expense_table_df.empty:
            st.dataframe(expense_table_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No expenses for the selected period.")

    with imports_tab:
        st.subheader("Latest Import Run", anchor=False)
        render_import_results()
        st.caption(
            "Automation is available with the fetch script or the systemd timer files "
            "in scripts/ for a server setup."
        )

finally:
    session.close()
