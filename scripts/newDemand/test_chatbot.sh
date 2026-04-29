#!/usr/bin/env bash
# Test the chatbot API

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/.env" | grep '=' | cut -d'=' -f1 | xargs)
fi

export DASHSCOPE_API_KEY="${OPENAI_API_KEY:-}"
export DASHSCOPE_BASE_URL="${OPENAI_BASE_URL:-}"
export DASHSCOPE_MODEL="${OPENAI_MODEL:-qwen3.6-plus}"

echo "Testing chatbot API..."
echo "======================"

RESPONSE=$(curl -s -X POST http://localhost:8899/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "AMZN 现在怎么样？当前走势如何？",
    "ticker": "AMZN"
  }')

echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
