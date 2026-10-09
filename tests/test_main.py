"""Tests for the CLI entry point in src/main.py."""

import sys
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pdfminer.pdfparser import PDFSyntaxError

from src import main


class DummySession:
    """Placeholder session object for patched tests."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _sample_invoice(serial="ri_test_001", total=7.90):
    return SimpleNamespace(
        serial_number=serial,
        period_start=date(2026, 2, 17),
        period_end=date(2026, 2, 21),
        invoice_date=date(2026, 2, 24),
        deliveries=[
            SimpleNamespace(
                day="Tuesday", date=date(2026, 2, 17), orders_delivered=1, total=4.51
            ),
        ],
        deliveries_total=4.51,
        adjustments=0.0,
        tips=3.39,
        grand_total=total,
    )


# ---------------------------------------------------------------------------
# print_invoice
# ---------------------------------------------------------------------------


def test_print_invoice_missing_file(capsys, tmp_path):
    missing = tmp_path / "missing.pdf"

    main.print_invoice(str(missing))

    out = capsys.readouterr().out
    assert f"Error: File not found: {missing}" in out


def test_print_invoice_non_pdf_suffix(capsys, tmp_path):
    txt_file = tmp_path / "note.txt"
    txt_file.write_text("not a pdf", encoding="utf-8")

    main.print_invoice(str(txt_file))

    out = capsys.readouterr().out
    assert f"Error: Not a PDF file: {txt_file}" in out


def test_print_invoice_parse_value_error(monkeypatch, capsys, tmp_path):
    pdf_file = tmp_path / "invoice.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(main, "parse_pdf", Mock(side_effect=ValueError("bad invoice")))

    main.print_invoice(str(pdf_file))

    out = capsys.readouterr().out
    assert f"Error parsing {pdf_file}: bad invoice" in out


def test_print_invoice_formats_full_invoice(monkeypatch, capsys, tmp_path):
    pdf_file = tmp_path / "invoice.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")
    invoice = _sample_invoice()
    monkeypatch.setattr(main, "parse_pdf", Mock(return_value=invoice))

    main.print_invoice(str(pdf_file))

    out = capsys.readouterr().out
    assert "Invoice: ri_test_001" in out
    assert "Period:  2026-02-17 to 2026-02-21" in out
    assert "Tuesday" in out
    assert "£   4.51" in out
    assert "TOTAL:" in out
    assert "£   7.90" in out


@pytest.mark.xfail(
    strict=True,
    raises=PDFSyntaxError,
    reason="print_invoice only catches ValueError, so a corrupt .pdf crashes with "
    "an uncaught PDFSyntaxError instead of printing a clean parse error",
)
def test_print_invoice_corrupt_pdf_prints_clean_error(capsys, tmp_path):
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"this is not a real pdf file")

    main.print_invoice(str(corrupt))

    out = capsys.readouterr().out
    assert "Error parsing" in out


# ---------------------------------------------------------------------------
# cmd_parse
# ---------------------------------------------------------------------------


def test_cmd_parse_no_args_prints_usage(capsys):
    main.cmd_parse([])

    out = capsys.readouterr().out
    assert "Usage: python -m src.main parse" in out


def test_cmd_parse_single_invoice_no_total_footer(monkeypatch, capsys, tmp_path):
    pdf_file = tmp_path / "invoice.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")
    invoice = _sample_invoice()
    monkeypatch.setattr(main, "parse_pdf", Mock(return_value=invoice))

    main.cmd_parse([str(pdf_file)])

    out = capsys.readouterr().out
    assert "Invoice: ri_test_001" in out
    assert "Total across" not in out


def test_cmd_parse_multiple_invoices_prints_total_footer(monkeypatch, capsys, tmp_path):
    pdf_a = tmp_path / "a.pdf"
    pdf_b = tmp_path / "b.pdf"
    pdf_a.write_bytes(b"%PDF-1.4")
    pdf_b.write_bytes(b"%PDF-1.4")
    invoice_a = _sample_invoice(serial="ri_a", total=10.0)
    invoice_b = _sample_invoice(serial="ri_b", total=5.5)
    monkeypatch.setattr(main, "parse_pdf", Mock(side_effect=[
        invoice_a, invoice_a, invoice_b, invoice_b
    ]))

    main.cmd_parse([str(pdf_a), str(pdf_b)])

    out = capsys.readouterr().out
    assert "Total across 2 invoices: £15.50" in out


def test_cmd_parse_mixed_batch_continues_after_errors(monkeypatch, capsys, tmp_path):
    """A missing file and a bad parse must not stop the rest of the batch."""
    missing = tmp_path / "missing.pdf"
    bad_pdf = tmp_path / "bad.pdf"
    good_pdf = tmp_path / "good.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4")
    good_pdf.write_bytes(b"%PDF-1.4")
    good_invoice = _sample_invoice(serial="ri_good", total=9.99)

    results_by_path = {
        str(bad_pdf): ValueError("Invalid invoice"),
        str(good_pdf): good_invoice,
    }

    def fake_parse_pdf(path):
        key = str(path)
        if key in results_by_path:
            value = results_by_path[key]
            if isinstance(value, Exception):
                raise value
            return value
        raise FileNotFoundError(f"No such file: {path}")

    monkeypatch.setattr(main, "parse_pdf", fake_parse_pdf)

    main.cmd_parse([str(missing), str(bad_pdf), str(good_pdf)])

    out = capsys.readouterr().out
    assert f"Error: File not found: {missing}" in out
    assert f"Error parsing {bad_pdf}: Invalid invoice" in out
    assert "Invoice: ri_good" in out
    # Only one invoice succeeded, so no multi-invoice footer is printed.
    assert "Total across" not in out


# ---------------------------------------------------------------------------
# cmd_save
# ---------------------------------------------------------------------------


def test_cmd_save_no_args_prints_usage_and_skips_db(monkeypatch, capsys):
    init_db = Mock()
    get_session = Mock()
    monkeypatch.setattr("src.db.init_db", init_db)
    monkeypatch.setattr("src.db.get_session", get_session)

    main.cmd_save([])

    out = capsys.readouterr().out
    assert "Usage: python -m src.main save" in out
    init_db.assert_not_called()
    get_session.assert_not_called()


def test_cmd_save_reports_saved_duplicate_and_error(monkeypatch, capsys):
    session = DummySession()
    monkeypatch.setattr("src.db.init_db", Mock())
    monkeypatch.setattr("src.db.get_session", Mock(return_value=session))

    results = [
        SimpleNamespace(
            status="saved", source_name="a.pdf", message="Saved",
            serial_number="ri_a", total=12.34, archived_path="data/invoices/2026/02/ri_a.pdf",
        ),
        SimpleNamespace(
            status="duplicate", source_name="b.pdf", message="Skipped duplicate",
            serial_number="ri_b", total=5.0, archived_path=None,
        ),
        SimpleNamespace(
            status="error", source_name="c.pdf", message="Could not parse invoice",
            serial_number=None, total=None, archived_path=None,
        ),
    ]
    monkeypatch.setattr(main, "import_pdf_paths", Mock(return_value=results))
    monkeypatch.setattr(main, "summarize_results", Mock(return_value={
        "saved": 1, "duplicate": 1, "error": 1, "invalid": 0,
    }))

    main.cmd_save(["a.pdf", "b.pdf", "c.pdf"])

    out = capsys.readouterr().out
    assert "Saved: ri_a (12.34)" in out
    assert "Skipped (duplicate): ri_b" in out
    assert "Skipping: c.pdf: Could not parse invoice" in out
    assert "Archived PDFs under:" in out
    assert "1 saved, 1 duplicates, 1 parse errors, 0 invalid files" in out
    assert session.closed is True


def test_cmd_save_closes_session_even_if_import_raises(monkeypatch):
    session = DummySession()
    monkeypatch.setattr("src.db.init_db", Mock())
    monkeypatch.setattr("src.db.get_session", Mock(return_value=session))
    monkeypatch.setattr(main, "import_pdf_paths", Mock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        main.cmd_save(["a.pdf"])

    assert session.closed is True


# ---------------------------------------------------------------------------
# _print_summary_table
# ---------------------------------------------------------------------------


def test_print_summary_table_empty_rows_with_total(capsys):
    main._print_summary_table([], total_label="Grand total", total=0.0)

    out = capsys.readouterr().out
    assert "Month" in out
    assert "Grand total: £0.00" in out


def test_print_summary_table_renders_rows_and_title(capsys):
    rows = [
        {"year": 2026, "month": 2, "invoice_count": 3, "total_earned": 45.5},
        {"year": 2026, "month": 3, "invoice_count": 1, "total_earned": 10.0},
    ]

    main._print_summary_table(
        rows, title="Custom Title", total_label="Total for 2026", total=55.5
    )

    out = capsys.readouterr().out
    assert "Custom Title" in out
    assert "February 2026" in out
    assert "March 2026" in out
    assert "Total for 2026: £55.50" in out


def test_print_summary_table_without_total_omits_footer(capsys):
    rows = [{"year": 2026, "month": 1, "invoice_count": 1, "total_earned": 1.0}]

    main._print_summary_table(rows)

    out = capsys.readouterr().out
    assert "January 2026" in out
    assert "Total" not in out


# ---------------------------------------------------------------------------
# cmd_summary
# ---------------------------------------------------------------------------


def _patch_db_summary(monkeypatch, session=None, **overrides):
    session = session or DummySession()
    monkeypatch.setattr("src.db.get_session", Mock(return_value=session))
    monkeypatch.setattr("src.db.get_summary", overrides.get("get_summary", Mock(return_value=[])))
    monkeypatch.setattr(
        "src.db.get_yearly_total", overrides.get("get_yearly_total", Mock(return_value=0.0))
    )
    monkeypatch.setattr(
        "src.db.get_summary_by_tax_year",
        overrides.get("get_summary_by_tax_year", Mock(return_value=[])),
    )
    monkeypatch.setattr(
        "src.db.get_tax_year_total", overrides.get("get_tax_year_total", Mock(return_value=0.0))
    )
    return session


def test_cmd_summary_empty_database(monkeypatch, capsys):
    session = _patch_db_summary(monkeypatch)

    main.cmd_summary([])

    out = capsys.readouterr().out
    assert "No invoices found in the database." in out
    assert session.closed is True


def test_cmd_summary_grand_total_from_all_rows(monkeypatch, capsys):
    rows = [
        {"year": 2025, "month": 12, "invoice_count": 2, "total_earned": 20.0},
        {"year": 2026, "month": 1, "invoice_count": 1, "total_earned": 5.0},
    ]
    _patch_db_summary(monkeypatch, get_summary=Mock(return_value=rows))

    main.cmd_summary([])

    out = capsys.readouterr().out
    assert "Grand total: £25.00" in out


def test_cmd_summary_year_filter_routes_to_yearly_total(monkeypatch, capsys):
    rows = [{"year": 2025, "month": 6, "invoice_count": 4, "total_earned": 40.0}]
    get_summary = Mock(return_value=rows)
    get_yearly_total = Mock(return_value=40.0)
    _patch_db_summary(monkeypatch, get_summary=get_summary, get_yearly_total=get_yearly_total)

    main.cmd_summary(["2025"])

    get_summary.assert_called_once_with(get_summary.call_args[0][0], 2025)
    get_yearly_total.assert_called_once_with(get_yearly_total.call_args[0][0], 2025)
    out = capsys.readouterr().out
    assert "Total for 2025: £40.00" in out


def test_cmd_summary_year_with_no_records(monkeypatch, capsys):
    _patch_db_summary(monkeypatch, get_summary=Mock(return_value=[]))

    main.cmd_summary(["2099"])

    out = capsys.readouterr().out
    assert "No invoices found in the database." in out


def test_cmd_summary_tax_mode_without_year_prints_usage(monkeypatch, capsys):
    get_summary_by_tax_year = Mock(return_value=[])
    _patch_db_summary(monkeypatch, get_summary_by_tax_year=get_summary_by_tax_year)

    main.cmd_summary(["--tax"])

    out = capsys.readouterr().out
    assert "Usage: python -m src.main summary --tax <start_year>" in out
    get_summary_by_tax_year.assert_not_called()


def test_cmd_summary_tax_mode_with_no_records(monkeypatch, capsys):
    _patch_db_summary(monkeypatch, get_summary_by_tax_year=Mock(return_value=[]))

    main.cmd_summary(["--tax", "2025"])

    out = capsys.readouterr().out
    assert "No invoices found for tax year 2025/2026." in out


def test_cmd_summary_tax_mode_with_records(monkeypatch, capsys):
    rows = [{"year": 2025, "month": 4, "invoice_count": 1, "total_earned": 8.5}]
    _patch_db_summary(
        monkeypatch,
        get_summary_by_tax_year=Mock(return_value=rows),
        get_tax_year_total=Mock(return_value=8.5),
    )

    main.cmd_summary(["--tax", "2025"])

    out = capsys.readouterr().out
    assert "Tax Year 2025/2026 (6 Apr 2025 - 5 Apr 2026)" in out
    assert "Total for tax year 2025/2026: £8.50" in out


@pytest.mark.xfail(
    strict=True,
    raises=ValueError,
    reason="cmd_summary does not validate the year argument and crashes with an "
    "uncaught ValueError instead of printing a usage error for non-numeric input",
)
def test_cmd_summary_non_numeric_year_prints_usage_error(monkeypatch, capsys):
    _patch_db_summary(monkeypatch)

    main.cmd_summary(["not-a-year"])

    out = capsys.readouterr().out
    assert "Error" in out or "Usage" in out


# ---------------------------------------------------------------------------
# cmd_fetch
# ---------------------------------------------------------------------------


def _patch_db_fetch(monkeypatch, sessions, latest_invoice_date=None):
    monkeypatch.setattr("src.db.init_db", Mock())
    monkeypatch.setattr("src.db.get_session", Mock(side_effect=sessions))
    monkeypatch.setattr(
        "src.db.get_latest_invoice_date", Mock(return_value=latest_invoice_date)
    )


def test_cmd_fetch_no_prior_invoices_searches_without_after_date(monkeypatch, capsys):
    session1 = DummySession()
    _patch_db_fetch(monkeypatch, sessions=[session1], latest_invoice_date=None)
    fetch_invoices = Mock(return_value=[])
    monkeypatch.setattr("src.email_fetcher.fetch_invoices", fetch_invoices)

    main.cmd_fetch([])

    out = capsys.readouterr().out
    assert "No saved invoices yet." in out
    fetch_invoices.assert_called_once_with(output_dir=None, after_date=None)
    assert session1.closed is True


def test_cmd_fetch_uses_lookback_window_from_latest_invoice(monkeypatch, capsys):
    session1 = DummySession()
    latest = date(2026, 1, 1)
    _patch_db_fetch(monkeypatch, sessions=[session1], latest_invoice_date=latest)
    fetch_invoices = Mock(return_value=[])
    monkeypatch.setattr("src.email_fetcher.fetch_invoices", fetch_invoices)
    monkeypatch.setenv("FETCH_LOOKBACK_DAYS", "10")

    main.cmd_fetch([])

    out = capsys.readouterr().out
    expected_after = latest - timedelta(days=10)
    assert expected_after.isoformat() in out
    assert latest.isoformat() in out
    fetch_invoices.assert_called_once_with(output_dir=None, after_date=expected_after)


def test_cmd_fetch_passes_output_dir_argument(monkeypatch):
    session1 = DummySession()
    _patch_db_fetch(monkeypatch, sessions=[session1], latest_invoice_date=None)
    fetch_invoices = Mock(return_value=[])
    monkeypatch.setattr("src.email_fetcher.fetch_invoices", fetch_invoices)

    main.cmd_fetch(["/tmp/custom_dir"])

    fetch_invoices.assert_called_once_with(output_dir="/tmp/custom_dir", after_date=None)


def test_cmd_fetch_saves_downloaded_pdfs(monkeypatch, capsys):
    session1 = DummySession()
    session2 = DummySession()
    _patch_db_fetch(monkeypatch, sessions=[session1, session2], latest_invoice_date=None)
    monkeypatch.setattr(
        "src.email_fetcher.fetch_invoices", Mock(return_value=["a.pdf", "b.pdf"])
    )
    results = [
        SimpleNamespace(
            status="saved", source_name="a.pdf", message="Saved",
            serial_number="ri_a", total=3.0, archived_path="data/invoices/2026/01/ri_a.pdf",
        ),
    ]
    monkeypatch.setattr(main, "import_pdf_paths", Mock(return_value=results))
    monkeypatch.setattr(main, "summarize_results", Mock(return_value={
        "saved": 1, "duplicate": 0, "error": 0, "invalid": 0,
    }))

    main.cmd_fetch([])

    out = capsys.readouterr().out
    assert "Saved: ri_a (3.00)" in out
    assert "Archived PDFs under:" in out
    assert session1.closed is True
    assert session2.closed is True


def test_cmd_fetch_no_pdfs_found_skips_second_session(monkeypatch, capsys):
    session1 = DummySession()
    get_session = Mock(return_value=session1)
    _patch_db_fetch(monkeypatch, sessions=[session1], latest_invoice_date=None)
    monkeypatch.setattr("src.db.get_session", get_session)
    monkeypatch.setattr("src.email_fetcher.fetch_invoices", Mock(return_value=[]))
    import_pdf_paths = Mock()
    monkeypatch.setattr(main, "import_pdf_paths", import_pdf_paths)

    main.cmd_fetch([])

    import_pdf_paths.assert_not_called()
    get_session.assert_called_once()


@pytest.mark.xfail(
    strict=True,
    raises=FileNotFoundError,
    reason="cmd_fetch does not catch missing Gmail credentials and crashes with an "
    "uncaught FileNotFoundError instead of printing a clean setup error",
)
def test_cmd_fetch_missing_credentials_prints_clean_error(monkeypatch, capsys):
    session1 = DummySession()
    _patch_db_fetch(monkeypatch, sessions=[session1], latest_invoice_date=None)
    monkeypatch.setattr(
        "src.email_fetcher.fetch_invoices",
        Mock(side_effect=FileNotFoundError(
            "Missing credentials.json. Download OAuth2 credentials from Google Cloud Console."
        )),
    )

    main.cmd_fetch([])

    out = capsys.readouterr().out
    assert "credentials" in out.lower()


# ---------------------------------------------------------------------------
# main() dispatch
# ---------------------------------------------------------------------------


def test_main_no_command_prints_usage_and_exits(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py"])

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Usage: python -m src.main <command> [args]" in out


def test_main_unknown_command_prints_usage_and_exits(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "bogus"])

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Usage: python -m src.main <command> [args]" in out


@pytest.mark.parametrize("command", ["parse", "save", "fetch", "summary"])
def test_main_dispatches_to_correct_command(monkeypatch, command):
    mock_cmd = Mock()
    monkeypatch.setitem(main.COMMANDS, command, mock_cmd)
    monkeypatch.setattr(sys, "argv", ["main.py", command, "arg1", "arg2"])

    main.main()

    mock_cmd.assert_called_once_with(["arg1", "arg2"])


def test_main_dispatches_with_no_extra_args(monkeypatch):
    mock_cmd = Mock()
    monkeypatch.setitem(main.COMMANDS, "summary", mock_cmd)
    monkeypatch.setattr(sys, "argv", ["main.py", "summary"])

    main.main()

    mock_cmd.assert_called_once_with([])
