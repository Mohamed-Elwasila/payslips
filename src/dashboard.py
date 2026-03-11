"""Streamlit dashboard for Deliveroo earnings."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd

from src.db import (
    get_session,
    get_summary,
    get_summary_by_tax_year,
    get_yearly_total,
    get_tax_year_total,
    get_all_invoices,
    _tax_year_dates,
)

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


st.set_page_config(page_title="Deliveroo Earnings", layout="wide")
st.title("Deliveroo Earnings Dashboard")

session = get_session()

try:
    # --- Sidebar filters ---
    st.sidebar.header("Filters")
    view_mode = st.sidebar.radio("View by", ["Calendar Year", "Tax Year"])

    all_summary = get_summary(session)
    if not all_summary:
        st.warning("No invoices found in the database.")
        st.stop()

    available_years = sorted(set(r["year"] for r in all_summary))

    if view_mode == "Calendar Year":
        selected_year = st.sidebar.selectbox(
            "Year", ["All"] + available_years
        )
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

    # --- Top-level metrics ---
    total_invoices = sum(r["invoice_count"] for r in rows)
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Earned", f"£{total:,.2f}")
    col2.metric("Invoices", total_invoices)
    col3.metric("Period", total_label)

    # --- Monthly earnings chart ---
    st.subheader("Monthly Earnings")
    if rows:
        df = pd.DataFrame(rows)
        df["month_label"] = df.apply(
            lambda r: f"{MONTH_NAMES[int(r['month'])]} {int(r['year'])}", axis=1
        )
        chart_data = df.set_index("month_label")["total_earned"]
        st.bar_chart(chart_data)

    # --- Monthly breakdown table ---
    st.subheader("Monthly Breakdown")
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

    # --- All invoices table ---
    st.subheader("All Invoices")
    invoices = get_all_invoices(session)
    if invoices:
        inv_df = pd.DataFrame(invoices)

        # Add tax week column
        inv_df["Tax Week"] = inv_df["invoice_date"].apply(lambda d: None)
        for idx, row in inv_df.iterrows():
            inv_date = row["invoice_date"]
            # Determine which tax year this invoice falls in
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

finally:
    session.close()
