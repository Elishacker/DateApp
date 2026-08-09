#!/usr/bin/env bash
# Runs the dev server over HTTPS on the LAN, so phone-based testing gets a
# secure context (needed for browser APIs like geolocation, which browsers
# refuse to expose over plain http on anything but localhost).
#
# The cert is self-signed, so the first visit from a phone/other browser
# shows a "connection is not private" warning — that's expected. Accepting
# it once is enough; the connection is genuinely encrypted from then on.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-8000}"
LAN_IP="$(hostname -I | awk '{print $1}')"
CERT_DIR="certs"
CERT="$CERT_DIR/dev-cert.pem"
KEY="$CERT_DIR/dev-key.pem"

mkdir -p "$CERT_DIR"

# Regenerated every run (cheap) so it always matches the current LAN IP —
# DHCP can hand out a new one between sessions.
openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY" -out "$CERT" \
    -days 825 \
    -subj "/CN=Zynora Dev" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:${LAN_IP}" \
    > /dev/null 2>&1

echo "Serving https://${LAN_IP}:${PORT}/ (and https://localhost:${PORT}/)"
echo "First load on another device will warn the cert isn't trusted — accept/proceed once."
echo

exec daphne \
    -e "ssl:${PORT}:privateKey=${KEY}:certKey=${CERT}:interface=0.0.0.0" \
    config.asgi:application
