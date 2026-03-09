# Payslips

Extract and track earnings from Deliveroo self-billing invoice PDFs.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

Parse a single invoice:

```bash
python -m src.main path/to/invoice.pdf
```

Parse multiple invoices:

```bash
python -m src.main invoices/*.pdf
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Roadmap

- [x] Phase 1: PDF parser (extract invoice data from Deliveroo PDFs)
- [ ] Phase 2: PostgreSQL storage (persist data, query totals)
- [ ] Phase 3: Gmail integration (auto-fetch invoice attachments)
- [ ] Phase 4: Weekly automation + yearly reporting
