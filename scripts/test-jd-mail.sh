#!/usr/bin/env bash
#
# test-jd-mail.sh — send a test email through all three sending domains
# from the JD-ERP VPS, using the live server .env / venv.
#
# Wraps:  manage.py send_test_mail  (apps/notifications)
# Runs as www-data so the chmod-600 server .env is readable and the
# transports use the production credentials.
#
# Usage (on the VPS, as root or via sudo):
#   /usr/local/bin/test-jd-mail you@example.com
#   /usr/local/bin/test-jd-mail you@example.com --only msg91
#
# Install once (mirrors the deploy-jd-erp convention):
#   sudo cp /var/www/jd-erp/scripts/test-jd-mail.sh /usr/local/bin/test-jd-mail
#   sudo chmod +x /usr/local/bin/test-jd-mail
#
set -euo pipefail

APP_DIR="/var/www/jd-erp"
PY="${APP_DIR}/venv/bin/python"
RUN_AS="www-data"

if [[ $# -lt 1 ]]; then
  echo "usage: $(basename "$0") <recipient-email> [--only jdindia|msg91|edu] [--msg91-template NAME]" >&2
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
    "${PY}" "${APP_DIR}/manage.py" send_test_mail "$@"
else
  exec "${PY}" "${APP_DIR}/manage.py" send_test_mail "$@"
fi
