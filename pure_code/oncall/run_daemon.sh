#!/bin/bash
# Run the on-call agent as a background daemon process

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "${SCRIPT_DIR}"

# Set PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:${SCRIPT_DIR}/src"

# Activate virtual environment
source venv/bin/activate

# Log file
LOG_FILE="${SCRIPT_DIR}/logs/agent_daemon.log"
PID_FILE="${SCRIPT_DIR}/logs/agent.pid"

# Create logs directory
mkdir -p logs

# Function to start daemon
start_daemon() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Agent is already running (PID: $PID)"
            exit 1
        else
            echo "Removing stale PID file..."
            rm "$PID_FILE"
        fi
    fi

    echo "Starting on-call agent daemon..."
    echo "Log file: $LOG_FILE"

    # Run orchestrator in background
    nohup python3 src/integrations/orchestrator.py > "$LOG_FILE" 2>&1 &

    # Save PID
    echo $! > "$PID_FILE"
    echo "Agent started (PID: $!)"
    echo ""
    echo "Monitor logs: tail -f $LOG_FILE"
    echo "Stop daemon: ./run_daemon.sh stop"
}

# Function to stop daemon
stop_daemon() {
    if [ ! -f "$PID_FILE" ]; then
        echo "Agent is not running (no PID file)"
        exit 1
    fi

    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Stopping agent (PID: $PID)..."
        kill "$PID"
        rm "$PID_FILE"
        echo "Agent stopped"
    else
        echo "Agent is not running (PID $PID not found)"
        rm "$PID_FILE"
    fi
}

# Function to check status
check_status() {
    if [ ! -f "$PID_FILE" ]; then
        echo "Agent is not running"
        exit 1
    fi

    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Agent is running (PID: $PID)"
        echo "Uptime: $(ps -o etime= -p "$PID")"
        echo "Log file: $LOG_FILE"
        echo ""
        echo "Recent logs:"
        tail -10 "$LOG_FILE"
    else
        echo "Agent is not running (stale PID file)"
        rm "$PID_FILE"
        exit 1
    fi
}

# Function to tail logs
tail_logs() {
    if [ ! -f "$LOG_FILE" ]; then
        echo "No log file found at $LOG_FILE"
        exit 1
    fi
    tail -f "$LOG_FILE"
}

# Main command handler
case "$1" in
    start)
        start_daemon
        ;;
    stop)
        stop_daemon
        ;;
    restart)
        stop_daemon
        sleep 2
        start_daemon
        ;;
    status)
        check_status
        ;;
    logs)
        tail_logs
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the agent daemon"
        echo "  stop    - Stop the agent daemon"
        echo "  restart - Restart the agent daemon"
        echo "  status  - Check if agent is running"
        echo "  logs    - Tail the agent logs"
        exit 1
        ;;
esac
