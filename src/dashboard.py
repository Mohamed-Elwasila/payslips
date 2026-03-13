"""Streamlit dashboard for Deliveroo earnings."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from src.db import (
    _tax_year_dates,
    get_all_invoices,
    get_session,
    get_summary,
    get_summary_by_tax_year,
    get_tax_year_total,
    get_yearly_total,
    init_db,
)
from src.importer import import_uploaded_pdfs, summarize_results

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def get_tax_week(invoice_date, tax_year_start):
    """Calculate UK tax week number (Week 1 starts 6 April)."""
    delta = invoice_date - tax_year_start
    if delta.days < 0:
        return None
    return delta.days // 7 + 1


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
    rows = []
    total = 0.0
    total_label = "No data yet"

    if all_summary:
        available_years = sorted(set(r["year"] for r in all_summary))

        if view_mode == "Calendar Year":
            selected_year = st.sidebar.selectbox("Year", ["All"] + available_years)
            if selected_year == "All":
                rows = all_summary
                total = sum(r["total_earned"] for r in rows)
                total_label = "All Time"
            else:
                rows = get_summary(session, year=selected_year)
                total = get_yearly_total(session, selected_year)
                total_label = str(selected_year)
        else:
            tax_years = sorted(set(
                y for y in range(min(available_years) - 1, max(available_years) + 1)
            ))
            tax_year_labels = [f"{y}/{y + 1}" for y in tax_years]
            selected_label = st.sidebar.selectbox("Tax Year", tax_year_labels)
            start_year = int(selected_label.split("/")[0])
            rows = get_summary_by_tax_year(session, start_year)
            total = get_tax_year_total(session, start_year)
            total_label = f"Tax Year {selected_label}"

    total_invoices = sum(r["invoice_count"] for r in rows)
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Earned", f"£{total:,.2f}")
    col2.metric("Invoices", total_invoices)
    col3.metric("Period", total_label)

    st.subheader("Import Status", anchor=False)
    render_import_results()

    st.subheader("Monthly Earnings", anchor=False)
    if rows:
        df = pd.DataFrame(rows)
        df["month_label"] = df.apply(
            lambda r: f"{MONTH_NAMES[int(r['month'])]} {int(r['year'])}", axis=1
        )
        chart_data = df.set_index("month_label")["total_earned"]
        st.bar_chart(chart_data)
    else:
        st.caption("No monthly earnings for the selected period.")

    st.subheader("Monthly Breakdown", anchor=False)
    if rows:
        table_df = pd.DataFrame(rows)
        table_df["Month"] = table_df.apply(
            lambda r: f"{MONTH_NAMES[int(r['month'])]} {int(r['year'])}", axis=1
        )
        table_df = table_df.rename(columns={
            "invoice_count": "Invoices",
            "total_earned": "Earned",
        })
        table_df["Earned"] = table_df["Earned"].apply(lambda x: f"£{x:,.2f}")
        st.dataframe(
            table_df[["Month", "Invoices", "Earned"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No monthly breakdown for the selected period.")

    st.subheader("All Invoices", anchor=False)
    invoices = get_all_invoices(session)
    if invoices:
        inv_df = pd.DataFrame(invoices)
        inv_df["Tax Week"] = inv_df["invoice_date"].apply(lambda d: None)
        for idx, row in inv_df.iterrows():
            inv_date = row["invoice_date"]
            if inv_date >= date(inv_date.year, 4, 6):
                ty_start = date(inv_date.year, 4, 6)
                ty_label = f"{inv_date.year}/{inv_date.year + 1}"
            else:
                ty_start = date(inv_date.year - 1, 4, 6)
                ty_label = f"{inv_date.year - 1}/{inv_date.year}"
            week = get_tax_week(inv_date, ty_start)
            inv_df.at[idx, "Tax Week"] = f"W{week} ({ty_label})"

        inv_df = inv_df.rename(columns={
            "serial_number": "Serial Number",
            "period_start": "Period Start",
            "period_end": "Period End",
            "invoice_date": "Invoice Date",
            "deliveries_total": "Deliveries",
            "tips": "Tips",
            "adjustments": "Adjustments",
            "grand_total": "Total",
        })
        for col in ["Deliveries", "Tips", "Adjustments", "Total"]:
            inv_df[col] = inv_df[col].apply(lambda x: f"£{x:,.2f}")
        st.dataframe(inv_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No invoices found in the database yet.")

finally:
    session.close()
