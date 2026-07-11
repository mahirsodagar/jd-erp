#!/usr/bin/env bash
#
# test-jd-wa.sh — send a test WhatsApp message through the live XIRCLS
# gateway from the JD-ERP VPS, using the server .env / venv and the
# production code path.
#
# Wraps:  manage.py send_test_wa  (apps/notifications)
# Runs as www-data so the chmod-600 server .env is readable and the
# gateway call uses the production XIRCLS credentials.
#
# A PASS means XIRCLS accepted the message; final delivery is in
# WhatsApp's DLR, not this response.
#
# Requires WHATSAPP_ENABLED=True plus XIRCLS_API_KEY,
# XIRCLS_WHATSAPP_PROJECT_KEY, and a mapped XIRCLS_TRIGGER_* for the
# template — otherwise the send returns a clear configuration error.
#
# Usage (on the VPS, as root or via sudo):
#   /usr/local/bin/test-jd-wa 9XXXXXXXXX
#   /usr/local/bin/test-jd-wa 9XXXXXXXXX --raw
#   /usr/local/bin/test-jd-wa 9XXXXXXXXX --template lead_welcome_wa \
#                                        --var name=Ayush --var program=Interior
#   /usr/local/bin/test-jd-wa --show          # list recent WA dispatch-log rows
#
# Install once (mirrors the deploy-jd-erp / test-jd-sms convention):
#   sudo cp /var/www/jd-erp/scripts/test-jd-wa.sh /usr/local/bin/test-jd-wa
#   sudo chmod +x /usr/local/bin/test-jd-wa
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
    "${PY}" "${APP_DIR}/manage.py" send_test_wa "$@"
else
  exec "${PY}" "${APP_DIR}/manage.py" send_test_wa "$@"
fi
