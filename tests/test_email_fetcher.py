"""Tests for Gmail fetch query construction."""

from datetime import date

from src.email_fetcher import search_deliveroo_emails


class _MessagesAPI:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def execute(self):
        return {"messages": [{"id": "abc123"}]}


class _UsersAPI:
    def __init__(self, messages_api):
        self._messages_api = messages_api

    def messages(self):
        return self._messages_api


class _Service:
    def __init__(self):
        self.messages_api = _MessagesAPI()

    def users(self):
        return _UsersAPI(self.messages_api)


def test_search_deliveroo_emails_without_after_date():
    service = _Service()

    messages = search_deliveroo_emails(service, max_results=25)

    assert messages == [{"id": "abc123"}]
    assert service.messages_api.calls == [{
        "userId": "me",
        "q": "from:deliveroo subject:invoice has:attachment filename:pdf",
        "maxResults": 25,
    }]


def test_search_deliveroo_emails_with_after_date():
    service = _Service()

    search_deliveroo_emails(
        service,
        max_results=10,
        after_date=date(2026, 2, 18),
    )

    assert service.messages_api.calls == [{
        "userId": "me",
        "q": (
            "from:deliveroo subject:invoice has:attachment filename:pdf "
            "after:2026/02/18"
        ),
        "maxResults": 10,
    }]
