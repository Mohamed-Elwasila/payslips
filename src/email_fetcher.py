"""
Gmail integration for fetching Deliveroo invoice PDF attachments.

Requires OAuth2 credentials from Google Cloud Console.
On first run, opens a browser for authentication and saves the token locally.

Setup:
1. Go to https://console.cloud.google.com/
2. Create a project (or use existing)
3. Enable the Gmail API
4. Create OAuth 2.0 credentials (Desktop app)
5. Download the JSON and save as credentials.json in the project root
"""

import base64
import os
import tempfile
from datetime import date
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_FILE = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.getenv("GMAIL_TOKEN_FILE", "token.json")


def get_gmail_service():
    """Authenticate and return a Gmail API service instance."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Missing {CREDENTIALS_FILE}. "
                    "Download OAuth2 credentials from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def search_deliveroo_emails(
    service,
    max_results: int = 50,
    after_date: date | None = None,
):
    """
    Search Gmail for Deliveroo invoice emails with PDF attachments.

    Returns a list of message IDs.
    """
    query = "from:deliveroo subject:invoice has:attachment filename:pdf"
    if after_date is not None:
        query = f"{query} after:{after_date.strftime('%Y/%m/%d')}"
    results = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    return results.get("messages", [])


def download_pdf_attachments(service, message_id: str, output_dir: str) -> list[str]:
    """
    Download all PDF attachments from a specific email message.

    Returns a list of file paths for downloaded PDFs.
    """
    message = service.users().messages().get(
        userId="me", id=message_id
    ).execute()

    downloaded = []
    payload = message.get("payload", {})
    parts = payload.get("parts", [])

    for part in parts:
        filename = part.get("filename", "")
        if not filename.lower().endswith(".pdf"):
            continue

        attachment_id = part.get("body", {}).get("attachmentId")
        if not attachment_id:
            continue

        attachment = service.users().messages().attachments().get(
            userId="me", messageId=message_id, id=attachment_id
        ).execute()

        file_data = base64.urlsafe_b64decode(attachment["data"])
        file_path = os.path.join(output_dir, filename)

        with open(file_path, "wb") as f:
            f.write(file_data)

        downloaded.append(file_path)

    return downloaded


def fetch_invoices(
    output_dir: str = None,
    max_results: int = 50,
    after_date: date | None = None,
) -> list[str]:
    """
    authenticate, search for Deliveroo emails, download all PDF attachments.

    Returns a list of downloaded PDF file paths.
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="deliveroo_invoices_")

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    service = get_gmail_service()
    messages = search_deliveroo_emails(
        service,
        max_results=max_results,
        after_date=after_date,
    )

    if not messages:
        print("No Deliveroo invoice emails found.")
        return []

    print(f"Found {len(messages)} Deliveroo email(s) with attachments.")

    all_pdfs = []
    for msg in messages:
        pdfs = download_pdf_attachments(service, msg["id"], output_dir)
        all_pdfs.extend(pdfs)

    print(f"Downloaded {len(all_pdfs)} PDF(s) to {output_dir}")
    return all_pdfs
