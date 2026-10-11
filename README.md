# Payslips

Extract and track earnings from Deliveroo self-billing invoice PDFs.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # edit credentials if needed
docker compose up -d         # start PostgreSQL
```

For Gmail auto-fetch: enable the Gmail API in
[Google Cloud Console](https://console.cloud.google.com/), create an OAuth2
Desktop app credential, and save it as `credentials.json` in the project
root. First run opens a browser to authenticate.

## Usage

```bash
python -m src.main parse path/to/invoice.pdf   # parse and display, no DB
python -m src.main save path/to/invoice.pdf    # parse and save to DB
python -m src.main fetch                       # fetch from Gmail, parse, save
python -m src.main summary --tax 2025          # UK tax year summary
```

Saved invoice PDFs are archived under `data/invoices/YYYY/MM/` for tax records.

## Automation

Cron and systemd units for scheduled fetching are in `scripts/`. I run mine
on an HP Mini PC via the systemd timer — it checks Gmail weekly and only
looks back as far as `FETCH_LOOKBACK_DAYS` from the last saved invoice, so
it stays fast once caught up. Swap in the cron script instead if you'd
rather not deal with systemd.

## Dashboard

```bash
streamlit run src/dashboard.py
```

![Payslips dashboard](docs/Payslips-framed.jpg)

- Upload invoices and track expenses (with receipts) from the sidebar
- Income, expenses, and profit by calendar year or UK tax year
- Docker Compose mounts `data/` on the host so archives survive container rebuilds

## Running Tests

```bash
python -m pytest tests/ -v
```
