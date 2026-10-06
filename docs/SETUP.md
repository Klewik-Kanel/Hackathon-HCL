# Setup guide

Two parts: the **AI model** runs on your laptop (Ollama), and **everything
else** runs in Docker. Do part 1 first; it is the slow download.

Time needed: about 15 minutes, most of it downloads.

---

## Part 1 — AI setup (Ollama + model), on the host laptop

Ollama runs the language model locally, so no internet or API key is
needed during the demo.

1. **Install Ollama**
   - Mac: `brew install ollama`, or download the app from https://ollama.com/download
   - Windows / Linux: installer from the same page

2. **Start the Ollama server** and leave this terminal open:
   ```bash
   ollama serve
   ```
   (If you installed the Mac app and it is running in the menu bar, skip this.)

3. **Download the model** in a second terminal (about 4.7 GB):
   ```bash
   ollama pull qwen2.5:7b-instruct
   ```
   Low on RAM (8 GB laptop)? Also pull the lighter backup:
   ```bash
   ollama pull qwen2.5:3b-instruct
   ```

4. **Quick test** that the model answers in JSON:
   ```bash
   ollama run qwen2.5:7b-instruct --format json "Return JSON with keys rule and value for: minimum attendance is 75 percent"
   ```
   You should see something like `{"rule": "minimum attendance", "value": "75%"}`.

5. **Full check with our code** (needs Python 3.10+ on the laptop):
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install httpx pydantic
   python scripts/check_ai_setup.py
   ```
   It prints OK lines and how many seconds one structured answer takes on
   this laptop. Over 20 seconds: switch to the 3B model in `.env`.

**Why qwen2.5:7b-instruct?** It is one of the two models the brief suggests,
and at this size it follows "reply in JSON" instructions more reliably
than llama3.1:8b, which matters because our planner and composer both
return JSON.

---

## Part 2 — Docker setup (API + UI)

1. **Install Docker Desktop** (https://www.docker.com/products/docker-desktop/)
   and start it. Give it at least 4 GB of memory in Settings → Resources.

2. **Create your settings file** (once):
   ```bash
   cp .env.example .env
   ```

3. **Build and start** (first build takes 5–10 minutes: it installs
   PyTorch for CPU and downloads the embedding model into the image):
   ```bash
   docker compose up --build
   ```

4. **Load the data** (in a second terminal, once the API is up; re-run after adding documents):
   ```bash
   docker compose exec api python scripts/bootstrap.py
   ```
   It indexes every document in `data/docs/` (download them first:
   [DATA_SOURCES.md](DATA_SOURCES.md)), loads the rule registry and the
   40 synthetic students.

5. **Check it works**
   - API health: open http://localhost:8000/health
     Every part should say `"status": "ok"`. If `llm` is `down`, Ollama is
     not running on the host or the model isn't pulled (Part 1).
   - API docs (try endpoints in the browser): http://localhost:8000/docs
   - Chat UI: http://localhost:8501

6. **Stop**: `Ctrl+C`, or `docker compose down`. Data in `./data`
   (vector store, SQLite) is kept between runs.

### How the containers reach Ollama

Inside a container, `localhost` means the container itself, not your
laptop. Docker gives the laptop the name `host.docker.internal`, and
`docker-compose.yml` sets `OLLAMA_HOST=http://host.docker.internal:11434`
for the API. On Linux the `extra_hosts` line in the compose file makes the
same name work.

---

## Part 3 — Running without Docker (for development)

Faster to iterate while coding:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python scripts/bootstrap.py              # index docs, load rules + students (once)
uvicorn app.main:app --reload            # API on :8000
pip install -r ui/requirements.txt
streamlit run ui/streamlit_app.py        # UI on :8501 (second terminal)
```

Regenerate the synthetic students with the real model (do this once on
the demo laptop, then update docs/data_card.md):

```bash
python scripts/generate_students.py      # uses Ollama; --offline for no model
python scripts/load_students.py
```

Testing without the model at all:

```bash
python -m pytest        # tests set MOCK_LLM and offline embeddings themselves
```

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `/health` shows `llm: down`, "Connection refused" | Ollama isn't running: `ollama serve` |
| `llm: down`, "model not pulled" | `ollama pull qwen2.5:7b-instruct` |
| Answers take over 30 s | Use `LLM_MODEL=qwen2.5:3b-instruct` in `.env`; close other apps |
| `docker compose up` fails on `env_file` | Update Docker Desktop (needs Compose 2.24+), or create an empty `.env` |
| Port 8000 or 8501 already in use | Stop the other app, or change the left number in `ports:` |
