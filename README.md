# Payslips

Extract and track earnings from Deliveroo self-billing invoice PDFs.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Database (PostgreSQL via Docker)

```bash
cp .env.example .env        # edit credentials if needed
docker compose up -d         # start PostgreSQL
```

### Gmail API (for auto-fetching invoices)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use existing)
3. Enable the **Gmail API**
4. Go to Credentials > Create Credentials > OAuth 2.0 Client ID (Desktop app)
5. Download the JSON and save as `credentials.json` in the project root
6. On first run, a browser window will open for authentication

## Usage

Parse and display an invoice (no database):

```bash
python -m src.main parse path/to/invoice.pdf
```

Parse and save to database:

```bash
python -m src.main save path/to/invoice.pdf
```

Fetch invoices from Gmail, parse, and save to database:

```bash
python -m src.main fetch
python -m src.main fetch ./my_invoices   # save PDFs to a specific folder
```

View earnings summary:

```bash
python -m src.main summary             # all time
python -m src.main summary 2026        # calendar year 2026
python -m src.main summary --tax 2025  # UK tax year 2025/2026 (6 Apr - 5 Apr)
```

## Running Tests

```bash
python -m pytest tests/ -v
```
