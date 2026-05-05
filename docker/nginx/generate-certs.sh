#!/usr/bin/env bash
# Generate a self-signed TLS certificate for local / staging use.
# For production, replace with certs from Let's Encrypt or your CA.
#
# Usage: bash docker/nginx/generate-certs.sh [domain]
# Default domain: localhost
#
# Output: docker/nginx/certs/server.crt + server.key

set -euo pipefail

DOMAIN="${1:-localhost}"
CERT_DIR="$(dirname "$0")/certs"

mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout "$CERT_DIR/server.key" \
  -out    "$CERT_DIR/server.crt" \
  -subj   "/C=VN/ST=HCM/L=HoChiMinh/O=MeetingAgent/CN=$DOMAIN" \
  -addext "subjectAltName=DNS:$DOMAIN,DNS:localhost,IP:127.0.0.1"

echo "Certificates written to $CERT_DIR/"
echo "  server.crt  (public)"
echo "  server.key  (private — do NOT commit)"
