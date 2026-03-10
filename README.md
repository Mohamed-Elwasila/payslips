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

## Usage

Parse and display an invoice (no database):

```bash
python -m src.main parse path/to/invoice.pdf
```

Parse and save to database:

```bash
python -m src.main save path/to/invoice.pdf
```

View earnings summary:

```bash
python -m src.main summary         # all time
python -m src.main summary 2026    # specific year
```

## Running Tests

```bash
python -m pytest tests/ -v
```