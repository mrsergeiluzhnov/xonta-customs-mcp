#!/usr/bin/env bash
# Reload the TN VED / ETT table. Run from cron, e.g. every night:
#   15 4 * * * /opt/xonta-customs/deploy/update_tariff.sh >> /var/log/xonta-customs-tariff.log 2>&1
#
# TARIFF_URL must point to an .xlsx/.csv export with columns for code, name and duty rate.
# Check the file once by hand before putting it on a schedule.
set -euo pipefail
: "${TARIFF_URL:?set TARIFF_URL}"
export XONTA_CUSTOMS_DATA="${XONTA_CUSTOMS_DATA:-/opt/xonta-customs/data}"
/opt/xonta-customs/venv/bin/xonta-customs-load-tariff --url "$TARIFF_URL" --source "$TARIFF_URL, $(date +%F)"
