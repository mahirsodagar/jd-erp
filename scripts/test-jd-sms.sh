#!/usr/bin/env bash
#
# test-jd-sms.sh — send a test SMS through the live gateway from the
# JD-ERP VPS, using the server .env / venv and the production code path.
#
# Wraps:  manage.py send_test_sms  (apps/notifications)
# Runs as www-data so the chmod-600 server .env is readable and the
# gateway call uses the production BulkSMS / MSG91 credentials.
#
# Usage (on the VPS, as root or via sudo):
#   /usr/local/bin/test-jd-sms 9XXXXXXXXX
#   /usr/local/bin/test-jd-sms 9XXXXXXXXX --raw
#   /usr/local/bin/test-jd-sms 9XXXXXXXXX --template attendance.student_absent_v2.sms \
#                                         --var name=Ayush --var date=2026-06-18 --var subject=Sketching
#   /usr/local/bin/test-jd-sms --show          # list recent SMS dispatch-log rows
#
# Install once (mirrors the deploy-jd-erp / test-jd-mail convention):
#   sudo cp /var/www/jd-erp/scripts/test-jd-sms.sh /usr/local/bin/test-jd-sms
#   sudo chmod +x /usr/local/bin/test-jd-sms
#
set -euo pipefail

APP_DIR="/var/www/jd-erp"
PY="${APP_DIR}/venv/bin/python"
RUN_AS="www-data"

if [[ $# -lt 1 ]]; then
  echo "usage: $(basename "$0") <mobile> [--template KEY] [--var k=v] [--raw]" >&2
  echo "       $(basename "$0") --show [N]" >&2
  exit 2
fi

if [[ ! -x "${PY}" ]]; then
  echo "error: ${PY} not found — is the venv at ${APP_DIR}/venv?" >&2
  exit 1
fi

# Run as www-data when invoked as root; otherwise run directly (assumes
# the current user can read the .env and reach the venv).
if [[ "$(id -un)" == "root" ]]; then
  exec sudo -u "${RUN_AS}" --preserve-env=PATH \
    "${PY}" "${APP_DIR}/manage.py" send_test_sms "$@"
else
  exec "${PY}" "${APP_DIR}/manage.py" send_test_sms "$@"
fi
