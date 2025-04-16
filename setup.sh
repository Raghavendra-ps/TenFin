#!/bin/bash
# TenFin Setup Script - Simplified Version
# Assumes dashboard.py and scrape.py handle their own relative paths using pathlib.
# Installs dependencies, creates directories, and sets up optional services.

# Stop on any error
set -e

# --- Configuration ---
CRON_SCHEDULE="0 2 * * *" # Run daily at 2 AM
SERVER_HOST="0.0.0.0"     # Listen on all network interfaces
SERVER_PORT="8000"        # Port for the dashboard web server
SYSTEMD_SERVICE_NAME="tenfin-dashboard" # Name for the systemd service

# --- Helper Functions ---
log_info() {
    echo "[INFO] $1"
}
log_warn() {
    echo "[WARN] $1" >&2
}
log_error() {
    echo "[ERROR] $1" >&2
    exit 1
}

# --- Initial Checks ---
log_info "Starting TenFin Setup..."

# Determine the script's absolute directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log_info "Script directory: $SCRIPT_DIR"

# Check essential commands
command -v python3 >/dev/null 2>&1 || log_error "python3 command not found. Please install Python 3."
command -v pip >/dev/null 2>&1 || log_error "pip command (for python3) not found. Please install python3-pip or ensure pip links to Python 3."

# Check for virtual environment (highly recommended)
if [ -z "$VIRTUAL_ENV" ]; then
    log_warn "Not running inside a Python virtual environment."
    log_warn "It is STRONGLY recommended to use a virtual environment:"
    log_warn "  1. cd $SCRIPT_DIR"
    log_warn "  2. python3 -m venv venv"
    log_warn "  3. source venv/bin/activate"
    log_warn "  4. ./setup.sh"
    # Decide whether to stop or continue if no venv
    # log_error "Aborting setup. Please use a virtual environment."
    read -p "Continue installation without a virtual environment? (y/N): " confirm_no_venv
    if [[ ! "$confirm_no_venv" =~ ^[Yy]$ ]]; then
        log_error "Setup aborted by user. Please use a virtual environment."
    fi
    log_warn "Proceeding without virtual environment..."
else
    log_info "Running inside virtual environment: $VIRTUAL_ENV"
fi

# Navigate to project directory
cd "$SCRIPT_DIR" || log_error "Failed to navigate to script directory: $SCRIPT_DIR"
log_info "Current directory: $(pwd)"

# --- Dependency Installation ---
if [ ! -f "requirements.txt" ]; then
    log_error "requirements.txt not found in $SCRIPT_DIR. Cannot install dependencies."
fi
log_info "Installing Python packages from requirements.txt..."
pip install -r requirements.txt || log_error "Failed to install requirements. Check requirements.txt and network connection."
log_info "Python packages installed successfully."

# Verify uvicorn installation (crucial for dashboard)
# Use command -v again *after* installation
UVICORN_EXEC=$(command -v uvicorn)
if [ -z "$UVICORN_EXEC" ]; then
    log_error "uvicorn command not found after 'pip install'. Ensure 'uvicorn' is in requirements.txt and installed correctly in the current environment."
fi
PYTHON_EXEC=$(command -v python3) # Get python path, should exist if we got this far
log_info "Using Python: $PYTHON_EXEC"
log_info "Using Uvicorn: $UVICORN_EXEC"

# --- Directory Creation ---
log_info "Creating necessary data and log directories..."
BASE_DATA_DIR="$SCRIPT_DIR/scraped_data"
FILTERED_PATH="$BASE_DATA_DIR/Filtered Tenders" # Used by dashboard.py
RAW_PAGES_DIR="$BASE_DATA_DIR/RawPages"       # Used by scrape.py
LOG_DIR="$SCRIPT_DIR/logs"                  # Used by scrape.py & cron

# Create all directories, including parents (-p), fail script if any creation fails
mkdir -p "$BASE_DATA_DIR" "$FILTERED_PATH" "$RAW_PAGES_DIR" "$LOG_DIR" || log_error "Failed to create one or more directories."

# Add READMEs for clarity
echo "Base directory for scraped data." > "$BASE_DATA_DIR/README.md"
echo "Stores filtered tender sets created via the dashboard." > "$FILTERED_PATH/README.md"
echo "Stores intermediate raw pages fetched by scrape.py." > "$RAW_PAGES_DIR/README.md"
echo "Contains logs, primarily from the scraper cron job." > "$LOG_DIR/README.md"
log_info "Directories created successfully."

# --- OS Detection & Specific Setup ---
IS_MAC=false
if [[ "$OSTYPE" == "darwin"* ]]; then
    IS_MAC=true
    log_info "Detected macOS."
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    IS_MAC=false
    log_info "Detected Linux."
else
    IS_MAC=false
    log_warn "Unsupported OS '$OSTYPE'. Attempting Linux setup..."
fi

# --- Setup for Linux ---
if [[ "$IS_MAC" == false ]]; then
    log_info "Performing Linux-specific setup (Cron job, Systemd service)..."

    # 1. Setup Cron Job for scrape.py
    log_info "Setting up cron job for scrape.py..."
    if command -v crontab >/dev/null 2>&1; then
        CRON_LOG_FILE="$LOG_DIR/scrape_cron.log"
        # Command executed by cron: cd to script dir, run python using the found executable
        CRON_JOB_CMD="cd \"$SCRIPT_DIR\" && \"$PYTHON_EXEC\" scrape.py"
        # Full cron line: schedule + command + redirect stdout/stderr to log file
        CRON_JOB_FULL_LINE="$CRON_SCHEDULE $CRON_JOB_CMD >> \"$CRON_LOG_FILE\" 2>&1"

        log_info "  Schedule: $CRON_SCHEDULE"
        log_info "  Command: $CRON_JOB_CMD"
        log_info "  Log File: $CRON_LOG_FILE"

        # Check if command already exists in crontab (ignores schedule/log changes)
        if ! (crontab -l 2>/dev/null | grep -Fq "$CRON_JOB_CMD"); then
            # Add the job
            (crontab -l 2>/dev/null; echo "$CRON_JOB_FULL_LINE") | crontab - || log_error "Failed to add cron job. Check permissions or crontab syntax."
            log_info "  ✅ Cron job added successfully."
        else
            log_info "  ℹ️ Cron job command already exists. Skipping add."
            log_warn "     Manually edit ('crontab -e') if schedule or log path needs changing."
        fi
    else
        log_warn "  'crontab' command not found. Skipping automatic cron job setup."
        log_warn "  Manually schedule: $CRON_SCHEDULE cd \"$SCRIPT_DIR\" && \"$PYTHON_EXEC\" scrape.py >> \"$LOG_DIR/scrape_cron.log\" 2>&1"
    fi

    # 2. Setup Systemd Service for dashboard.py
    log_info "Setting up systemd service for dashboard.py..."
    # Check if systemd is likely the init system
    if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
        log_info "  Systemd detected. Creating service '$SYSTEMD_SERVICE_NAME'..."
        SYSTEMD_SERVICE_FILE="/etc/systemd/system/${SYSTEMD_SERVICE_NAME}.service"

        # Create the service file using sudo and tee
        # Runs as the user executing setup.sh
        # Uses the uvicorn found in the current environment (respects venv)
        sudo tee "$SYSTEMD_SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=TenFin Dashboard FastAPI Service
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$SCRIPT_DIR
ExecStart=$UVICORN_EXEC dashboard:app --host $SERVER_HOST --port $SERVER_PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

        if [ $? -ne 0 ]; then
            log_error "Failed to write systemd service file ($SYSTEMD_SERVICE_FILE). Check sudo permissions."
        fi
        log_info "  Service file created: $SYSTEMD_SERVICE_FILE"

        # Reload, enable, and restart the service
        log_info "  Reloading systemd daemon, enabling and restarting service..."
        sudo systemctl daemon-reload || log_error "systemctl daemon-reload failed."
        sudo systemctl enable "$SYSTEMD_SERVICE_NAME" || log_error "systemctl enable failed for $SYSTEMD_SERVICE_NAME."
        sudo systemctl restart "$SYSTEMD_SERVICE_NAME" || log_error "systemctl restart failed for $SYSTEMD_SERVICE_NAME."
        log_info "  ✅ Systemd service '$SYSTEMD_SERVICE_NAME' enabled and started/restarted."

    else
        log_warn "  Systemd not detected. Skipping automatic service setup."
        log_warn "  To run the dashboard server:"
        log_warn "    cd $SCRIPT_DIR"
        log_warn "    # Run in foreground (for testing):"
        log_warn "    $UVICORN_EXEC dashboard:app --host $SERVER_HOST --port $SERVER_PORT"
        log_warn "    # Run in background (using nohup):"
        log_warn "    nohup $UVICORN_EXEC dashboard:app --host $SERVER_HOST --port $SERVER_PORT &"
        log_warn "    # (Using screen or tmux is recommended for better background management)"
    fi

# --- Instructions for macOS ---
elif [[ "$IS_MAC" == true ]]; then
    log_info "macOS detected. Manual setup needed for background services:"
    log_info "  Scraper Scheduling:"
    log_info "    Use 'launchd' to schedule scrape.py. Create a .plist file in ~/Library/LaunchAgents/"
    log_info "    Example command to run: cd \"$SCRIPT_DIR\" && \"$PYTHON_EXEC\" scrape.py >> \"$LOG_DIR/scrape_cron.log\" 2>&1"
    log_info "  Dashboard Service:"
    log_info "    Use 'launchd' to run dashboard.py on startup. Create a .plist file."
    log_info "    Example command to run: cd \"$SCRIPT_DIR\" && \"$UVICORN_EXEC\" dashboard:app --host $SERVER_HOST --port $SERVER_PORT"
    log_info "  Manual Execution:"
    log_info "    Scraper: cd \"$SCRIPT_DIR\" && \"$PYTHON_EXEC\" scrape.py"
    log_info "    Dashboard: cd \"$SCRIPT_DIR\" && \"$UVICORN_EXEC\" dashboard:app --host 127.0.0.1 --port $SERVER_PORT"
fi

# --- Final Summary ---
echo ""
log_info "✅ Setup script finished."
log_info "--------------------------------------------------"
if [[ "$IS_MAC" == false ]]; then
    log_info "Linux Summary:"
    log_info " - Scraper scheduled via cron (check 'crontab -l'). Logs in '$LOG_DIR/scrape_cron.log'."
    if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
       log_info " - Dashboard running as systemd service '$SYSTEMD_SERVICE_NAME'."
       log_info "   Manage: sudo systemctl [status|stop|start|restart] $SYSTEMD_SERVICE_NAME"
       log_info "   Logs:   sudo journalctl -u $SYSTEMD_SERVICE_NAME -f"
    else
       log_info " - Dashboard needs to be started manually (see instructions above)."
    fi
else
     log_info "macOS Summary:"
     log_info " - Scraper and Dashboard need manual setup using 'launchd' (see instructions above)."
fi
log_info " - Dashboard should be accessible at: http://localhost:$SERVER_PORT"
log_info "   (or http://<YOUR_SERVER_IP>:$SERVER_PORT if accessing remotely)"
log_info "--------------------------------------------------"

exit 0
