# Moodle LLM Assistant (Course RAG + Global Chat)

This repository contains a Moodle **block plugin** (`block_llmassistant`) plus a lightweight **RAG (Retrieval-Augmented Generation)** service that runs **inside the Moodle `webserver` container**. The assistant can:

- Provide a **per-course chat** (uses only that course’s PDFs)
- Provide a **global chat** (intended for faculty rules/norms)
- Show **sources** (PDF names)
- Run a **teacher-aware** extraction mode for questions like “Who are the teachers of this course?”

> **Important**: The RAG API (`uvicorn`) must be running for Moodle to receive answers.

---

## 1) Prerequisites

### Windows
- Docker Desktop installed and running
- WSL2 enabled with Ubuntu distro
- Ollama installed

### WSL (Ubuntu)
- Docker CLI available inside WSL (enable Docker Desktop WSL integration)

---

## 2) Expected repository layout

In WSL:

```bash
cd ~/dev/moodle-lab
ls
```

Expected folders:
- `moodle/` (Moodle code)
- `moodle-docker/` (moodle-docker environment)
- `moodle/blocks/llmassistant/` (plugin)
- `moodle/blocks/llmassistant/rag/` (RAG Python scripts)

---

## 3) Start Moodle (moodle-docker)

```bash
cd ~/dev/moodle-lab/moodle-docker

export MOODLE_DOCKER_WWWROOT=../moodle
export MOODLE_DOCKER_DB=pgsql

bin/moodle-docker-compose up -d
bin/moodle-docker-wait-for-db
```

Open Moodle:
- http://localhost:8000

---

## 4) Start Ollama + pull models (Windows PowerShell)

```powershell
# Confirm Ollama is reachable
curl.exe http://localhost:11434/api/tags

# Pull required models
ollama pull llama3.2
ollama pull nomic-embed-text
```

### If WSL/containers cannot reach Ollama (Windows Firewall)

Run PowerShell **as Administrator**:

```powershell
netsh advfirewall firewall add rule name="AllowOllamaWSL" dir=in action=allow protocol=TCP localport=11434
netsh advfirewall firewall add rule name="AllowOllamaWSL_out" dir=out action=allow protocol=TCP localport=11434
```

---

## 5) Install/upgrade the Moodle plugin

After copying the plugin into `moodle/blocks/llmassistant`:

1) Purge caches:
- **Site administration → Development → Purge caches**

2) Trigger install/upgrade:
- http://localhost:8000/admin/index.php

---

## 6) Chroma persistence (IMPORTANT)

Chroma persistence must live inside **moodledata** (persistent), not under `/`.

Create the folder inside the container (one time):

```bash
cd ~/dev/moodle-lab/moodle-docker
bin/moodle-docker-compose exec webserver bash -lc "mkdir -p /var/www/moodledata/chroma_db && chmod 777 /var/www/moodledata/chroma_db"
```

Make sure both scripts use this path:

```python
CHROMA_DB_PATH = "/var/www/moodledata/chroma_db"
```

---

## 7) Copy scripts into the container

From WSL:

```bash
# Ingest script
docker cp ~/dev/moodle-lab/moodle/blocks/llmassistant/rag/rag_ingest_moodle.py \
  moodle-docker-webserver-1:/rag_ingest_moodle.py

# API script
docker cp ~/dev/moodle-lab/moodle/blocks/llmassistant/rag/rag_api.py \
  moodle-docker-webserver-1:/var/www/html/blocks/llmassistant/rag/rag_api.py
```

(Optional) remove any old duplicate API file if you previously copied `/rag_api.py`:

```bash
cd ~/dev/moodle-lab/moodle-docker
bin/moodle-docker-compose exec webserver bash -lc "rm -f /rag_api.py"
```

---

## 8) Install Python dependencies inside the container (one time)

```bash
cd ~/dev/moodle-lab/moodle-docker
bin/moodle-docker-compose exec webserver bash -lc "pip3 install fastapi uvicorn chromadb requests psycopg2-binary PyMuPDF --break-system-packages"
```

---

## 9) Re-ingest course PDFs (per-course vector DB)

(Optional) wipe the persisted Chroma DB directory (safe reset):

```bash
cd ~/dev/moodle-lab/moodle-docker
bin/moodle-docker-compose exec webserver bash -lc "rm -rf /var/www/moodledata/chroma_db/*"
```

Run ingestion:

```bash
cd ~/dev/moodle-lab/moodle-docker
bin/moodle-docker-compose exec webserver bash -lc "python3 /rag_ingest_moodle.py"
```

Expected output:
- Creates/loads `course_docs_<courseid>` (e.g., `course_docs_2`)
- Processes course PDFs

---

## 10) Start the RAG API inside the container (port 8001)

### 10.1 Stop any previous API process

```bash
cd ~/dev/moodle-lab/moodle-docker
bin/moodle-docker-compose exec webserver bash -lc "pkill -f 'uvicorn rag_api:app' || true"
```

### 10.2 Start in background (recommended)

```bash
cd ~/dev/moodle-lab/moodle-docker
bin/moodle-docker-compose exec webserver bash -lc "cd /var/www/html/blocks/llmassistant/rag && nohup uvicorn rag_api:app --host 0.0.0.0 --port 8001 > /tmp/rag_api.log 2>&1 &"
```

Check logs:

```bash
cd ~/dev/moodle-lab/moodle-docker
bin/moodle-docker-compose exec webserver bash -lc "tail -n 80 /tmp/rag_api.log"
```

---

## 11) Test the RAG API

Inside the container:

```bash
cd ~/dev/moodle-lab/moodle-docker
bin/moodle-docker-compose exec webserver bash -lc "curl -X POST http://127.0.0.1:8001/ask -H 'Content-Type: application/json' -d '{\"question\":\"Who are the teachers of this course?\",\"courseid\":2,\"userid\":1}'"
```

Expected:
- JSON with `answer` and `sources`

---

## 12) Use the UI in Moodle

### Sidebar block
- Add the **LLM Assistant** block to a course page
- Ask questions in the sidebar
- Click **Open** to switch to the center panel chat

### Center panel: course chat

Open:
- `http://localhost:8000/blocks/llmassistant/chat.php?courseid=2`

Replace `2` with your Moodle course id.

### Center panel: global chat

Open:
- `http://localhost:8000/blocks/llmassistant/global.php`

Global chat uses `courseid=0` and is intended for faculty rules/norms. (You can ingest a `global_docs` collection later.)

---

## 13) Troubleshooting

### “Thinking…” never ends
- Ensure the API is running:

```bash
bin/moodle-docker-compose exec webserver bash -lc "curl -s -X POST http://127.0.0.1:8001/ask -H 'Content-Type: application/json' -d '{\"question\":\"ping\",\"courseid\":2,\"userid\":1}'"
```

- Check API logs:

```bash
bin/moodle-docker-compose exec webserver bash -lc "tail -n 200 /tmp/rag_api.log"
```

### Port 8001 already in use

```bash
bin/moodle-docker-compose exec webserver bash -lc "pkill -f 'uvicorn rag_api:app' || true"
```

### Ollama not reachable from the container

```bash
bin/moodle-docker-compose exec webserver bash -lc "curl http://host.docker.internal:11434/api/tags"
```

If it fails, re-check the Windows firewall rules in section 4.

---

## 14) Notes

- Per-course chat uses collection: `course_docs_<courseid>`
- Global chat uses collection: `global_docs` (to be ingested)
- Chat history persistence (one conversation per course) can be added next (Moodle DB table + endpoints).




## OLLAMA (PowerShell):

# Allow scripts (only once, for current user)
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# Run (pull models + optionally firewall rules)
.\start.ps1 -PullModels -EnsureFirewallRules


# RUN
chmod +x ~/dev/moodle-lab/start.sh
~/dev/moodle-lab/start.sh

# STOP RUN:
chmod +x ~/dev/moodle-lab/stop.sh
~/dev/moodle-lab/stop.sh

# STATUS:
chmod +x ~/dev/moodle-lab/status.sh
~/dev/moodle-lab/status.sh

# RESTART API:
chmod +x ~/dev/moodle-lab/restart_rag.sh
~/dev/moodle-lab/restart_rag.sh


# New PDF ingestion:
cd ~/dev/moodle-lab/moodle-docker
bin/moodle-docker-compose exec webserver bash -lc "python3 /rag_ingest_moodle.py"


# Total reset:
cd ~/dev/moodle-lab/moodle-docker
bin/moodle-docker-compose exec webserver bash -lc "rm -rf /var/www/moodledata/chroma_db/*"
bin/moodle-docker-compose exec webserver bash -lc "python3 /rag_ingest_moodle.py"

# COPY

docker cp ~/dev/moodle-lab/moodle/blocks/llmassistant/rag/rag_api.py moodle-docker-webserver-1:/var/www/html/blocks/llmassistant/rag/rag_api.py
docker cp ~/dev/moodle-lab/moodle/blocks/llmassistant/rag/rag_ingest_global.py   moodle-docker-webserver-1:/rag_ingest_global.py
docker cp ~/dev/moodle-lab/moodle/blocks/llmassistant/rag/rag_ingest_moodle.py moodle-docker-webserver-1:/rag_ingest_moodle.py

Recomendações práticas:

Quando ligares o PC: start.ps1 (Windows) + start.sh (WSL)
Quando quiseres ver se está tudo ok: status.sh
Quando quiseres parar tudo: stop.sh
Quando só a API está marada: restart_rag.sh

# RUN API:
cd moodle-docker
bin/moodle-docker-compose exec webserver bash

cd /var/www/html/blocks/llmassistant/rag
uvicorn rag_api:app --host 0.0.0.0 --port 8001