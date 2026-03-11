#!/usr/bin/env bash
# Weekly cron script to fetch Deliveroo invoices from Gmail and save to DB.
#
# Setup:
#   crontab -e
#   0 9 * * 1 /path/to/payslips/scripts/fetch_weekly.sh
#
# This runs every Monday at 9:00 AM.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/fetch.log"

mkdir -p "$PROJECT_DIR/logs"

echo "========================================" >> "$LOG_FILE"
echo "Fetch started: $(date)" >> "$LOG_FILE"

cd "$PROJECT_DIR"
source "$PROJECT_DIR/venv/bin/activate"

python -m src.main fetch >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "Fetch finished: $(date) (exit code: $EXIT_CODE)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

exit $EXIT_CODE
