"""Gmail response fixtures exercise fetching without network or credentials."""

import base64
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.email_fetcher import download_pdf_attachments, search_deliveroo_emails


def service_with_parts(parts):
    service = Mock()
    messages = service.users.return_value.messages.return_value
    messages.get.return_value.execute.return_value = {"payload": {"parts": parts}}
    messages.attachments.return_value.get.return_value.execute.return_value = {
        "data": base64.urlsafe_b64encode(b"invoice bytes").decode()
    }
    return service


def test_empty_mailbox():
    service = Mock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {}
    assert search_deliveroo_emails(service) == []


def test_download_pdf_and_ignore_non_pdf(tmp_path):
    service = service_with_parts([
        {"filename": "invoice.PDF", "body": {"attachmentId": "pdf"}},
        {"filename": "note.txt", "body": {"attachmentId": "text"}},
    ])
    paths = download_pdf_attachments(service, "message", str(tmp_path))
    assert len(paths) == 1
    assert Path(paths[0]).read_bytes() == b"invoice bytes"
    service.users.return_value.messages.return_value.attachments.return_value.get.assert_called_once_with(
        userId="me", messageId="message", id="pdf"
    )


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Search ignores nextPageToken")
def test_search_reads_next_page():
    service = Mock()
    request = service.users.return_value.messages.return_value.list
    request.return_value.execute.side_effect = [
        {"messages": [{"id": "first"}], "nextPageToken": "next"},
        {"messages": [{"id": "second"}]},
    ]
    assert search_deliveroo_emails(service) == [{"id": "first"}, {"id": "second"}]
    assert request.call_args.kwargs["pageToken"] == "next"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Nested MIME parts are ignored")
def test_nested_pdf_is_downloaded(tmp_path):
    service = service_with_parts([{"parts": [
        {"filename": "invoice.pdf", "body": {"attachmentId": "pdf"}}
    ]}])
    paths = download_pdf_attachments(service, "message", str(tmp_path))
    assert len(paths) == 1
    assert Path(paths[0]).read_bytes() == b"invoice bytes"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Same-name attachments overwrite each other")
def test_same_filename_from_two_messages_is_preserved(tmp_path):
    service = service_with_parts([
        {"filename": "invoice.pdf", "body": {"attachmentId": "pdf"}}
    ])
    attachment = service.users.return_value.messages.return_value.attachments.return_value.get
    attachment.return_value.execute.side_effect = [
        {"data": base64.urlsafe_b64encode(content).decode()}
        for content in (b"first", b"second")
    ]
    first = download_pdf_attachments(service, "first", str(tmp_path))
    second = download_pdf_attachments(service, "second", str(tmp_path))
    assert Path(first[0]).read_bytes() == b"first"
    assert Path(second[0]).read_bytes() == b"second"
