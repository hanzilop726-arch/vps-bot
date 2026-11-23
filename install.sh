#!/bin/bash

set -e

REPO="https://github.com/hanzilop726-arch/vps-bot.git"
INSTALL_DIR="/opt/discord-vps-bot"
SERVICE_NAME="discord-vps-bot"

echo "========================================"
echo "     MineHosting VPS Bot Installer"
echo "========================================"

if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run this installer as root."
    exit 1
fi

echo "[1/7] Updating packages..."
apt-get update -y

echo "[2/7] Installing required packages..."
apt-get install -y \
    git \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    python3-venv \
    docker.io

echo "[3/7] Starting Docker..."
systemctl enable --now docker

echo "[4/7] Downloading VPS Bot..."

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Existing installation found."

    cd "$INSTALL_DIR"

    if [ -f ".env" ]; then
        cp .env /tmp/vps-bot-env.backup
    fi

    git fetch origin
    git reset --hard origin/main

    if [ -f /tmp/vps-bot-env.backup ]; then
        cp /tmp/vps-bot-env.backup .env
    fi
else
    rm -rf "$INSTALL_DIR"
    git clone "$REPO" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

echo "[5/7] Installing Python dependencies..."

python3 -m venv .venv

.venv/bin/pip install --upgrade pip

.venv/bin/pip install \
    "discord.py>=2.4,<3" \
    "docker>=7,<8" \
    "python-dotenv>=1,<2"

echo "[6/7] Building VPS Docker image..."

docker build \
    -t minehosting-vps:latest \
    "$INSTALL_DIR"

echo "[7/7] Creating systemd service..."

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=MineHosting Discord VPS Bot
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/python ${INSTALL_DIR}/discord.py
Restart=always
RestartSec=5
EnvironmentFile=${INSTALL_DIR}/.env

[Install]
WantedBy=multi-user.target
EOF

chmod 600 "$INSTALL_DIR/.env"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo ""
echo "========================================"
echo "      Installation Complete!"
echo "========================================"
echo ""
echo "Bot directory:"
echo "  $INSTALL_DIR"
echo ""
echo "Service:"
echo "  $SERVICE_NAME"
echo ""
echo "Status:"
systemctl --no-pager --full status "$SERVICE_NAME" || true

echo ""
echo "Useful commands:"
echo "  systemctl status $SERVICE_NAME"
echo "  systemctl restart $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f"
echo ""
echo "========================================"
