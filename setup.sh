#!/bin/bash

# Self-make this script executable (if not already)
chmod +x "$0"

# Navigate to TenFin project directory
cd /Systems_Engineer/TenFin || {
    echo "❌ Directory /Systems_Engineer/TenFin not found."
    exit 1
}

echo "📦 Installing Python requirements..."
if ! pip install -r requirements.txt; then
    echo "❌ Failed to install requirements."
    exit 1
fi

echo "⚙️ Setting up 'tenfin' command..."

# Create the CLI helper
cat <<EOF | sudo tee /usr/local/bin/tenfin > /dev/null
#!/bin/bash
cd /Systems_Engineer/TenFin
case "\$1" in
    start)
        uvicorn dashboard:app --reload --host 0.0.0.0 --port 8000
        ;;
    *)
        echo "Usage: tenfin start"
        ;;
esac
EOF

sudo chmod +x /usr/local/bin/tenfin
echo "✅ 'tenfin' command is now available."

echo "🛠️ Creating systemd service..."

# Create systemd service unit
cat <<EOF | sudo tee /etc/systemd/system/tenfin.service > /dev/null
[Unit]
Description=TenFin FastAPI Service
After=network.target

[Service]
Type=simple
WorkingDirectory=/Systems_Engineer/TenFin
ExecStart=/usr/local/bin/tenfin start
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reexec
sudo systemctl daemon-reload

echo "✅ Systemd service created. You can now run:"
echo "   sudo systemctl start tenfin"
echo "   sudo systemctl status tenfin"

# === Add cron job for scrape.py at 12:00 AM ===
CRON_JOB="0 0 * * * cd /Systems_Engineer/TenFin && /usr/bin/python3 scrape.py >> /Systems_Engineer/TenFin/scrape.log 2>&1"

# Check if already present
( crontab -l 2>/dev/null | grep -v 'scrape.py' ; echo "$CRON_JOB" ) | crontab -

echo "🕛 Scheduled scrape.py to run daily at 12:00 AM via cron."
