#!/usr/bin/env bash
# Start the whole app on this laptop without Docker:
#   bash scripts/run_local.sh
#
# 1. creates .venv and installs dependencies (first run only, ~5 min)
# 2. checks Ollama; if it is not running or the model is missing, the app
#    starts in MOCK mode (keyword fallback, no LLM) and tells you so
# 3. indexes the documents and loads rules + students (bootstrap)
# 4. stops any old Docker copy of the app, then starts the API on :8000
#    and the chat UI on :8501
# Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${LLM_MODEL:-qwen2.5:7b-instruct}"
PY="${PYTHON:-python3}"

if [ ! -d .venv ]; then
  echo "==> Creating virtual environment (.venv)"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import fastapi, chromadb, sentence_transformers, langgraph, streamlit" 2>/dev/null; then
  echo "==> Installing dependencies (first run only)"
  pip install -q --upgrade pip
  if [ "$(uname)" = "Darwin" ]; then pip install -q torch; else pip install -q torch --index-url https://download.pytorch.org/whl/cpu; fi
  pip install -q -r requirements.txt -r ui/requirements.txt
fi

# An older copy of the app started with `docker compose up` holds ports
# 8000/8501 and answers "501: Not built yet". Stop it first.
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  OLD=$(docker ps -q --filter publish=8000; docker ps -q --filter publish=8501)
  if [ -n "$OLD" ]; then
    echo "==> Stopping old Docker containers on ports 8000/8501"
    docker stop $OLD >/dev/null
  fi
fi
for PORT in 8000 8501; do
  if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "!!  Port $PORT is still in use by:"; lsof -nP -iTCP:$PORT -sTCP:LISTEN | tail -n +2
    echo "    Close that program (or run: kill \$(lsof -t -iTCP:$PORT -sTCP:LISTEN)) and run this script again."
    exit 1
  fi
done

export OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
if ! curl -s "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && command -v ollama >/dev/null 2>&1; then
  echo "==> Starting Ollama"
  (ollama serve > .ollama.log 2>&1 &)
  for _ in $(seq 1 15); do curl -s "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break; sleep 1; done
fi
if curl -s "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  if curl -s "$OLLAMA_HOST/api/tags" | grep -q "\"$MODEL\""; then
    echo "==> Ollama is running with $MODEL"
    export MOCK_LLM="${MOCK_LLM:-false}"
  else
    echo "!!  Ollama is running but $MODEL is not pulled. Run: ollama pull $MODEL"
    echo "    Starting in MOCK mode for now."
    export MOCK_LLM=true
  fi
else
  echo "!!  Ollama is not running (start it with: ollama serve). Starting in MOCK mode for now."
  export MOCK_LLM=true
fi

echo "==> Loading documents, rules and students"
python scripts/bootstrap.py

echo "==> Starting API on http://localhost:8000"
uvicorn app.main:app --host 127.0.0.1 --port 8000 > .api.log 2>&1 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT
for _ in $(seq 1 60); do curl -s 127.0.0.1:8000/health >/dev/null 2>&1 && break; sleep 1; done
curl -s 127.0.0.1:8000/health | python -m json.tool | head -30 || { echo "!! API did not start, see .api.log"; tail -20 .api.log; exit 1; }

echo ""
echo "==> Chat UI: http://localhost:8501   (Ctrl+C to stop)"
echo "    Log in with a student ID (S1001-S1040) and the starting password: ${DEMO_PASSWORD:-nsut@123}"
API_URL=http://127.0.0.1:8000 streamlit run ui/streamlit_app.py --server.headless true
