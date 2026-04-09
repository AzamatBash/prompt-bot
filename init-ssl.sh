#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────
DOMAIN="${1:?Usage: ./init-ssl.sh <domain> [email]}"
EMAIL="${2:-}"
COMPOSE="docker compose"

echo "==> Domain: $DOMAIN"
echo "==> Email:  ${EMAIL:-<not set, will use --register-unsafely-without-email>}"

# ── 1. Create dummy certificate so nginx can start ─────
echo "==> Creating dummy certificate for $DOMAIN..."
$COMPOSE run --rm --entrypoint "" certbot sh -c "
    mkdir -p /etc/letsencrypt/live/$DOMAIN &&
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
        -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem \
        -out    /etc/letsencrypt/live/$DOMAIN/fullchain.pem \
        -subj   '/CN=localhost'
"

# ── 2. Start nginx with dummy cert ────────────────────
echo "==> Starting nginx..."
$COMPOSE up -d nginx

# ── 3. Remove dummy certificate ───────────────────────
echo "==> Removing dummy certificate..."
$COMPOSE run --rm --entrypoint "" certbot sh -c "
    rm -rf /etc/letsencrypt/live/$DOMAIN &&
    rm -rf /etc/letsencrypt/archive/$DOMAIN &&
    rm -rf /etc/letsencrypt/renewal/$DOMAIN.conf
"

# ── 4. Request real certificate from Let's Encrypt ────
echo "==> Requesting certificate from Let's Encrypt..."
EMAIL_ARG=""
if [ -n "$EMAIL" ]; then
    EMAIL_ARG="--email $EMAIL"
else
    EMAIL_ARG="--register-unsafely-without-email"
fi

$COMPOSE run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    -d "$DOMAIN" \
    $EMAIL_ARG \
    --agree-tos \
    --no-eff-email \
    --force-renewal

# ── 5. Reload nginx with real certificate ─────────────
echo "==> Reloading nginx..."
$COMPOSE exec nginx nginx -s reload

echo ""
echo "==> Done! SSL certificate installed for $DOMAIN"
echo "==> Now start all services: docker compose up -d"
