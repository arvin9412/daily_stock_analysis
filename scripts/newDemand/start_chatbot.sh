#!/usr/bin/env bash
# Load .env and start chatbot server
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

cd "$SCRIPT_DIR"

# Source .env properly (handles quotes, comments, etc.)
while IFS='=' read -r key value; do
    # Skip comments and empty lines
    case "$key" in
        \#*|"") continue ;;
    esac
    # Remove leading/trailing whitespace and quotes
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | sed 's/^["'"'"']//;s/["'"'"']$//')
    export "$key=$value"
done < <(grep -v '^\s*#' "$PROJECT_DIR/.env" | grep '=')

# Map project env vars to chatbot vars
export DASHSCOPE_API_KEY="${OPENAI_API_KEY}"
export DASHSCOPE_BASE_URL="${OPENAI_BASE_URL}"
export DASHSCOPE_MODEL="${OPENAI_MODEL}"

# Auto-activate venv from project root if it exists
if [ -d "$PROJECT_DIR/venv" ]; then
    echo "Activating virtual environment at $PROJECT_DIR/venv..."
    source "$PROJECT_DIR/venv/bin/activate"
fi

echo "=== Env Check ==="
echo "OPENAI_BASE_URL=$OPENAI_BASE_URL"
echo "DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY:0:8}..."
echo "================="

# Restart logic: kill existing process on port 8899
PORT=8899
echo "Checking for existing process on port $PORT..."
EXISTING_PID=$(lsof -ti :$PORT)
if [ -n "$EXISTING_PID" ]; then
    echo "Stopping existing chatbot server (PID: $EXISTING_PID)..."
    kill -9 $EXISTING_PID
    sleep 1
fi

echo "Starting Chatbot Server..."
python3 chatbot_server.py "$@"
