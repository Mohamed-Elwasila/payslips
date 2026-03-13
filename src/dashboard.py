"""Streamlit dashboard for Deliveroo earnings."""

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
    get_invoices_by_tax_year,
    get_invoices_by_year,
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


def build_monthly_chart(rows):
    """Return a compact monthly earnings chart with trend line."""
    monthly_df = pd.DataFrame(rows)
    monthly_df["month_label"] = monthly_df.apply(
        lambda r: format_month_label(r["year"], r["month"]), axis=1
    )
    monthly_df["sort_date"] = pd.to_datetime(
        monthly_df["year"].astype(int).astype(str)
        + "-"
        + monthly_df["month"].astype(int).astype(str).str.zfill(2)
        + "-01"
    )
    order = monthly_df.sort_values("sort_date")["month_label"].tolist()

    bars = alt.Chart(monthly_df).mark_bar(
        cornerRadiusTopLeft=4,
        cornerRadiusTopRight=4,
        color="#2F6DB4",
    ).encode(
        x=alt.X(
            "month_label:N",
            sort=order,
            axis=alt.Axis(labelAngle=0, title=None, labelLimit=140),
        ),
        y=alt.Y("total_earned:Q", title="Earned (£)"),
        tooltip=[
            alt.Tooltip("month_label:N", title="Month"),
            alt.Tooltip("invoice_count:Q", title="Invoices"),
            alt.Tooltip("total_earned:Q", title="Earned", format=",.2f"),
        ],
    )

    trend = alt.Chart(monthly_df).mark_line(
        color="#17324D",
        point=True,
        strokeWidth=2,
    ).encode(
        x=alt.X("month_label:N", sort=order),
        y=alt.Y("total_earned:Q"),
    )

    return (bars + trend).properties(height=160)


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
    invoices = []
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
                invoices = get_all_invoices(session)
            else:
                rows = get_summary(session, year=selected_year)
                total = get_yearly_total(session, selected_year)
                total_label = str(selected_year)
                invoices = get_invoices_by_year(session, selected_year)
        else:
            tax_years = sorted(
                set(
                    y for y in range(
                        min(available_years) - 1,
                        max(available_years) + 1,
                    )
                ),
                reverse=True,
            )
            tax_year_labels = [f"{y}/{y + 1}" for y in tax_years]
            selected_label = st.sidebar.selectbox("Tax Year", tax_year_labels)
            start_year = int(selected_label.split("/")[0])
            rows = get_summary_by_tax_year(session, start_year)
            total = get_tax_year_total(session, start_year)
            total_label = f"Tax Year {selected_label}"
            invoices = get_invoices_by_tax_year(session, start_year)

    overview_tab, invoices_tab, imports_tab = st.tabs(
        ["Overview", "Invoices", "Imports"]
    )

    with overview_tab:
        total_invoices = len(invoices)
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Earned", f"£{total:,.2f}")
        col2.metric("Invoices", total_invoices)
        col3.metric("Period", total_label)

        st.subheader("Monthly Earnings", anchor=False)
        if rows:
            st.altair_chart(build_monthly_chart(rows), use_container_width=True)
        else:
            st.caption("No monthly earnings for the selected period.")

        st.subheader("Monthly Breakdown", anchor=False)
        if rows:
            table_df = pd.DataFrame(rows)
            table_df["Month"] = table_df.apply(
                lambda r: format_month_label(r["year"], r["month"]), axis=1
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

    with imports_tab:
        st.subheader("Latest Import Run", anchor=False)
        render_import_results()
        st.caption(
            "Automation is available with the fetch script or the systemd timer files "
            "in scripts/ for a server setup."
        )

finally:
    session.close()
