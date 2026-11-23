#!/bin/bash

set -e

REPO="https://github.com/hanzilop726-arch/vps-bot.git"
INSTALL_DIR="/opt/discord-vps-bot"
SERVICE_NAME="discord-vps-bot"

echo ""
echo "=============================================="
echo "       MineHosting Discord VPS Bot"
echo "              Installer"
echo "=============================================="
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run this installer as root."
    exit 1
fi

echo "[1/8] Updating system packages..."
apt-get update -y

echo ""
echo "[2/8] Installing required packages..."

apt-get install -y \
    git \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    python3-venv \
    docker.io

echo ""
echo "[3/8] Starting Docker..."

systemctl enable --now docker

echo ""
echo "[4/8] Downloading MineHosting VPS Bot..."

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Existing installation detected."
    cd "$INSTALL_DIR"

    if [ -f ".env" ]; then
        cp .env /tmp/discord-vps-bot.env.backup
    fi

    git fetch origin
    git reset --hard origin/main

    if [ -f /tmp/discord-vps-bot.env.backup ]; then
        cp /tmp/discord-vps-bot.env.backup .env
    fi
else
    rm -rf "$INSTALL_DIR"
    git clone "$REPO" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

echo ""
echo "[5/8] Installing Python dependencies..."

python3 -m venv .venv

.venv/bin/pip install --upgrade pip

.venv/bin/pip install \
    "discord.py>=2.4,<3" \
    "docker>=7,<8" \
    "python-dotenv>=1,<2"

echo ""
echo "[6/8] Building VPS Docker image..."

docker build \
    -t minehosting-vps:latest \
    "$INSTALL_DIR"

echo ""
echo "=============================================="
echo "          BOT CONFIGURATION"
echo "=============================================="
echo ""

while true; do
    read -rsp "Enter Discord Bot Token: " DISCORD_TOKEN
    echo ""

    if [ -n "$DISCORD_TOKEN" ]; then
        break
    fi

    echo "❌ Bot token cannot be empty."
done

while true; do
    read -rp "Enter Admin Discord ID: " ADMIN_ID

    if [[ "$ADMIN_ID" =~ ^[0-9]+$ ]]; then
        break
    fi

    echo "❌ Please enter a valid numeric Discord ID."
done

while true; do
    read -rp "Enter VPS Public IPv4: " PUBLIC_IP

    if [[ "$PUBLIC_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        break
    fi

    echo "❌ Please enter a valid IPv4 address."
done

echo ""
echo "[7/8] Creating .env..."

cat > "$INSTALL_DIR/.env" <<EOF
DISCORD_TOKEN=$DISCORD_TOKEN

PUBLIC_IP=$PUBLIC_IP

ADMIN_IDS=$ADMIN_ID

PORT_START=20000
PORT_END=30000
EOF

chmod 600 "$INSTALL_DIR/.env"

echo "✅ .env configured."

echo ""
echo "[8/8] Creating systemd service..."

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=MineHosting Discord VPS Bot
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/discord.py
EnvironmentFile=$INSTALL_DIR/.env
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo ""
echo "=============================================="
echo "        INSTALLATION COMPLETED"
echo "=============================================="
echo ""
echo "📁 Bot Directory:"
echo "   $INSTALL_DIR"
echo ""
echo "🐳 Docker Image:"
echo "   minehosting-vps:latest"
echo ""
echo "⚙️ Service:"
echo "   $SERVICE_NAME"
echo ""
echo "🤖 Bot Status:"
systemctl --no-pager --full status "$SERVICE_NAME" || true
echo ""
echo "=============================================="
echo "Useful Commands"
echo "=============================================="
echo ""
echo "Status:"
echo "  systemctl status $SERVICE_NAME"
echo ""
echo "Restart:"
echo "  systemctl restart $SERVICE_NAME"
echo ""
echo "Logs:"
echo "  journalctl -u $SERVICE_NAME -f"
echo ""
echo "Stop:"
echo "  systemctl stop $SERVICE_NAME"
echo ""
echo "=============================================="
