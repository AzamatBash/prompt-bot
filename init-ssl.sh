#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:?Usage: ./init-ssl.sh <domain> [email]}"
EMAIL="${2:-}"
COMPOSE="docker compose"

echo "==> Domain: $DOMAIN"

# ── 1. Start services with HTTP-only config ────────────
echo "==> Starting services..."
$COMPOSE up -d

echo "==> Waiting for nginx to be ready..."
sleep 3

# ── 2. Request certificate from Let's Encrypt ─────────
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
    --no-eff-email

# ── 3. Generate HTTPS nginx config ────────────────────
echo "==> Switching nginx to HTTPS..."
cat > nginx/nginx.conf <<NGINXEOF
worker_processes auto;

events {
    worker_connections 1024;
}

http {
    sendfile        on;
    keepalive_timeout 65;

    log_format main '\$remote_addr - [\$time_local] "\$request" \$status \$body_bytes_sent';
    access_log /var/log/nginx/access.log main;
    error_log  /var/log/nginx/error.log warn;

    upstream bot_upstream {
        server bot:8000;
    }

    server {
        listen 80;
        server_name ${DOMAIN};

        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }

        location / {
            return 301 https://\$host\$request_uri;
        }
    }

    server {
        listen 443 ssl;
        server_name ${DOMAIN};

        ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;
        ssl_session_cache shared:SSL:10m;
        ssl_session_timeout 10m;

        client_max_body_size 10m;

        location /telegram/webhook {
            proxy_pass         http://bot_upstream;
            proxy_set_header   Host \$host;
            proxy_set_header   X-Real-IP \$remote_addr;
            proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header   X-Forwarded-Proto \$scheme;
            proxy_read_timeout 60s;
        }

        location /yookassa/webhook {
            proxy_pass         http://bot_upstream;
            proxy_set_header   Host \$host;
            proxy_set_header   X-Real-IP \$remote_addr;
            proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header   X-Forwarded-Proto \$scheme;
            proxy_read_timeout 60s;
        }

        location / {
            return 444;
        }
    }
}
NGINXEOF

# ── 4. Reload nginx with HTTPS config ─────────────────
$COMPOSE restart nginx

echo ""
echo "==> Done! HTTPS is active for $DOMAIN"
echo "==> Don't forget to set PUBLIC_BASE_URL=https://$DOMAIN in .env and restart bot:"
echo "    docker compose restart bot"
