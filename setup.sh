#!/bin/bash
# TenFin Setup Script

# Stop on any error
set -e

# Determine the script's directory
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Navigate to the project directory
cd "$SCRIPT_DIR" || {
    echo "❌ Failed to navigate to script directory: $SCRIPT_DIR"
    exit 1
}
echo "📍 Project directory: $(pwd)"

# 1. Install requirements.txt
echo "📦 Installing Python requirements..."
pip install -r requirements.txt || {
    echo "❌ Failed to install requirements."
    exit 1
}

# 2. Make a directory that stores scraper.py's web scraped data
SCRAPED_DATA_DIR="$SCRIPT_DIR/scraped_data"
echo "📁 Creating scraped data directory: $SCRAPED_DATA_DIR"
mkdir -p "$SCRAPED_DATA_DIR" || {
    echo "❌ Failed to create scraped data directory."
    exit 1
}

# 3. Update the base path in dashboard.py
DASHBOARD_PY="$SCRIPT_DIR/dashboard.py"
echo "🔨 Updating BASE_PATH in $DASHBOARD_PY..."
python3 -c "
filepath = '$DASHBOARD_PY'
new_base_path = '$SCRAPED_DATA_DIR'
with open(filepath, 'r') as f:
    lines = f.readlines()
with open(filepath, 'w') as f:
    for line in lines:
        if line.startswith('BASE_PATH ='):
            f.write(f'BASE_PATH = \"{new_base_path}\"\\n')
        else:
            f.write(line)
" || {
    echo "❌ Failed to update BASE_PATH in dashboard.py using Python."
    exit 1
}
# Delete the temporary file
rm -f "$DASHBOARD_PY.tmp"

# 4. Add a cron job to run scrape.py
CRON_SCHEDULE="0 0 * * *"
CRON_JOB="cd \"$SCRIPT_DIR\" && /usr/bin/python3 scrape.py >> \"$SCRAPED_DATA_DIR/scrape.log\" 2>&1"
echo "🕛 Adding cron job to run scrape.py: $CRON_JOB"
if ! (crontab -l | grep -q "$CRON_JOB"); then
    (crontab -l 2>/dev/null; echo "$CRON_SCHEDULE $CRON_JOB") | crontab || {
        echo "❌ Failed to add cron job."
        exit 1
    }
else
    echo "✅ Cron job already exists."
fi

# 5. Create tenfin as a service
SYSTEMD_SERVICE_NAME="tenfin"
SYSTEMD_SERVICE_FILE="/etc/systemd/system/${SYSTEMD_SERVICE_NAME}.service"
echo "⚙️ Creating systemd service: $SYSTEMD_SERVICE_FILE"

# Find the uvicorn executable
UVICORN_PATH=$(which uvicorn)
if [ -z "$UVICORN_PATH" ]; then
    echo "❌ uvicorn not found in PATH.  Please ensure it is installed and accessible."
    exit 1
fi
echo "📍 uvicorn found at: $UVICORN_PATH"

cat <<EOF | sudo tee "$SYSTEMD_SERVICE_FILE" > /dev/null
[Unit]
Description=TenFin FastAPI Service
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$UVICORN_PATH dashboard:app --reload --host 0.0.0.0 --port 8000
Restart=on-failure
User=root
Environment="SCRAPED_DATA_DIR=$SCRAPED_DATA_DIR" # Pass the variable

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload || {
    echo "❌ Failed to reload systemd daemon."
    exit 1
}
sudo systemctl enable "$SYSTEMD_SERVICE_NAME" || {
    echo "❌ Failed to enable $SYSTEMD_SERVICE_NAME service."
    exit 1
}
sudo systemctl start "$SYSTEMD_SERVICE_NAME" || {
    echo "❌ Failed to start $SYSTEMD_SERVICE_NAME service."
    exit 1
}

echo "✅ TenFin setup complete!"
echo "👉  To check the service status: sudo systemctl status $SYSTEMD_SERVICE_NAME"
echo "👉  To view scraper logs: tail -f $SCRAPED_DATA_DIR/scrape.log"
