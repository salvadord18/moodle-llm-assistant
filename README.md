# Moodle LLM Assistant

`block_llmassistant` is a Moodle block plugin that provides an LLM-based assistant for Moodle courses. It uses a Retrieval-Augmented Generation (RAG) architecture to answer questions using course materials and Moodle-native content.

The plugin includes:

- A Moodle block interface for course pages.
- A course chat page.
- A global chat page.
- A Python RAG API built with FastAPI/Uvicorn.
- A Moodle ingestion script that indexes course documents and Moodle-native content into ChromaDB.
- Source display for retrieved documents.

> **Important:** the Moodle plugin does not answer questions by itself. The Python RAG API must be running, and the Moodle course content must be ingested before the assistant can answer properly.

---

## 1. Architecture

The system has three main components:

```text
Moodle plugin → RAG API → ChromaDB + LLM model
```

Typical same-server deployment:

```text
Moodle server
├── Moodle plugin: /var/www/html/blocks/llmassistant
├── RAG API: http://127.0.0.1:8001/ask
├── ChromaDB: /var/www/moodledata/chroma_db
└── LLM endpoint: Ollama or compatible service
```

The Moodle plugin sends user questions to the RAG API. The RAG API retrieves relevant course content from ChromaDB and sends the retrieved context to an LLM model. The final answer and sources are returned to Moodle.

---

## 2. Requirements

### Moodle server

- Moodle installed and working.
- Access to the Moodle web root.
- Access to the Moodle database.
- Access to `moodledata`.
- Ability to install Moodle plugins.
- Python 3.10+ recommended.
- `pip`.
- A running LLM endpoint, for example Ollama.

### Python packages

The RAG service requires:

```text
fastapi
uvicorn
chromadb
requests
psycopg2-binary
PyMuPDF
beautifulsoup4
```

Install them with:

```bash
cd /var/www/html/blocks/llmassistant/rag
pip3 install -r requirements.txt
```

If no `requirements.txt` is available, install manually:

```bash
pip3 install fastapi uvicorn chromadb requests psycopg2-binary PyMuPDF beautifulsoup4
```

---

## 3. Installing the Moodle plugin

Copy the plugin folder to:

```bash
/var/www/html/blocks/llmassistant
```

The final path should look like:

```text
/var/www/html/blocks/llmassistant/version.php
/var/www/html/blocks/llmassistant/block_llmassistant.php
/var/www/html/blocks/llmassistant/rag/rag_api.py
/var/www/html/blocks/llmassistant/rag/rag_ingest_moodle.py
```

Then, as Moodle administrator:

1. Go to `Site administration`.
2. Open `Notifications`, or access:

```text
/admin/index.php
```

3. Follow the Moodle plugin installation/upgrade process.
4. Purge caches if needed:

```text
Site administration → Development → Purge caches
```

---

## 4. Plugin configuration

Configure the RAG API URL in the plugin settings.

Recommended same-server value:

```text
http://127.0.0.1:8001/ask
```

If the RAG API is hosted on another internal server:

```text
http://rag-server.internal:8001/ask
```

Do not expose the RAG API publicly unless proper authentication, firewall rules, and HTTPS are configured.

---

## 5. RAG configuration

The RAG scripts use environment variables for configuration.

### Moodle database

```bash
export MOODLE_DB_HOST=localhost
export MOODLE_DB_PORT=5432
export MOODLE_DB_NAME=moodle
export MOODLE_DB_USER=moodle
export MOODLE_DB_PASSWORD=CHANGE_ME
export MOODLE_DB_PREFIX=m_
```

### Moodle data paths

```bash
export MOODLEDATA_PATH=/var/www/moodledata/filedir
export CHROMA_DB_PATH=/var/www/moodledata/chroma_db
```

Create the ChromaDB directory:

```bash
mkdir -p /var/www/moodledata/chroma_db
chown -R www-data:www-data /var/www/moodledata/chroma_db
chmod -R 775 /var/www/moodledata/chroma_db
```

### LLM endpoint

If using Ollama locally:

```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
```

If using Ollama on another server:

```bash
export OLLAMA_BASE_URL=http://ollama-server.internal:11434
```

### LLM model

The model can be changed through:

```bash
export OLLAMA_LLM_MODEL=qwen2.5:3b
```

For better results, especially with tables and structured course schedules, a stronger model may be used if the server has enough memory/GPU resources.

Examples:

```bash
export OLLAMA_LLM_MODEL=llama3.1:8b
export OLLAMA_LLM_MODEL=qwen2.5:7b
```

The default model can also be changed directly in `rag_api.py`, but using environment variables is recommended.

---

## 6. Pulling the LLM model

If using Ollama, pull the chosen model:

```bash
ollama pull qwen2.5:3b
```

Optional embedding or alternative models may also be pulled depending on the configuration.

Check if Ollama is reachable:

```bash
curl http://127.0.0.1:11434/api/tags
```

---

## 7. Ingesting Moodle course content

Before using the assistant, the Moodle course content must be indexed.

Run:

```bash
cd /var/www/html/blocks/llmassistant/rag

export MOODLEDATA_PATH=/var/www/moodledata/filedir
export CHROMA_DB_PATH=/var/www/moodledata/chroma_db

export MOODLE_DB_HOST=localhost
export MOODLE_DB_PORT=5432
export MOODLE_DB_NAME=moodle
export MOODLE_DB_USER=moodle
export MOODLE_DB_PASSWORD=CHANGE_ME
export MOODLE_DB_PREFIX=m_

python3 rag_ingest_moodle.py
```

This creates one Chroma collection per Moodle course:

```text
course_docs_<courseid>
```

Example:

```text
course_docs_5
```

### Ingest a single course

```bash
TARGET_COURSE_ID=5 python3 rag_ingest_moodle.py
```

### Rebuild a single course collection

```bash
TARGET_COURSE_ID=5 RESET_COLLECTION=true python3 rag_ingest_moodle.py
```

### Rebuild all collections

```bash
RESET_COLLECTION=true python3 rag_ingest_moodle.py
```

Re-run ingestion whenever course materials are added, removed, or updated.

---

## 8. Starting the RAG API manually

For testing:

```bash
cd /var/www/html/blocks/llmassistant/rag

export CHROMA_DB_PATH=/var/www/moodledata/chroma_db
export MOODLEDATA_PATH=/var/www/moodledata/filedir
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_LLM_MODEL=qwen2.5:3b

uvicorn rag_api:app --host 127.0.0.1 --port 8001
```

If the Moodle server needs to access the API from another machine, use:

```bash
uvicorn rag_api:app --host 0.0.0.0 --port 8001
```

Only use `0.0.0.0` if firewall and network access are properly controlled.

---

## 9. Running the RAG API as a system service

Create:

```bash
/etc/systemd/system/moodle-llmassistant-rag.service
```

Example service:

```ini
[Unit]
Description=Moodle LLM Assistant RAG API
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/html/blocks/llmassistant/rag

Environment=CHROMA_DB_PATH=/var/www/moodledata/chroma_db
Environment=MOODLEDATA_PATH=/var/www/moodledata/filedir

Environment=MOODLE_DB_HOST=localhost
Environment=MOODLE_DB_PORT=5432
Environment=MOODLE_DB_NAME=moodle
Environment=MOODLE_DB_USER=moodle
Environment=MOODLE_DB_PASSWORD=CHANGE_ME
Environment=MOODLE_DB_PREFIX=m_

Environment=OLLAMA_BASE_URL=http://127.0.0.1:11434
Environment=OLLAMA_LLM_MODEL=qwen2.5:3b

ExecStart=/usr/bin/python3 -m uvicorn rag_api:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable moodle-llmassistant-rag
sudo systemctl start moodle-llmassistant-rag
sudo systemctl status moodle-llmassistant-rag
```

View logs:

```bash
journalctl -u moodle-llmassistant-rag -f
```

---

## 10. Testing the RAG API

Test with:

```bash
curl -X POST http://127.0.0.1:8001/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Who are the teachers of this course?","courseid":5,"userid":1}'
```

Expected response:

```json
{
  "answer": "...",
  "sources": []
}
```

If the answer says that no information was found, check:

1. The course id exists.
2. The course has been ingested.
3. The Chroma collection exists.
4. The RAG API can access the LLM endpoint.
5. The Moodle database credentials are correct.

---

## 11. Using the assistant in Moodle

### Course chat

Open a course page and add the `LLM Assistant` block.

The assistant will use the current course id and retrieve information from:

```text
course_docs_<courseid>
```

### Dedicated course chat page

Example:

```text
/blocks/llmassistant/chat.php?courseid=5
```

### Global chat

Example:

```text
/blocks/llmassistant/global.php
```

The global chat uses `courseid=0`. It should be configured with the intended institutional/global source collection.

---

## 12. Re-indexing strategy

The ingestion script should be re-run when:

- new PDFs are uploaded;
- Moodle labels/pages/books are changed;
- assignments or dates are updated;
- a course is imported or restored;
- the RAG logic is changed significantly.

Recommended manual re-index for one course:

```bash
TARGET_COURSE_ID=5 RESET_COLLECTION=true python3 rag_ingest_moodle.py
```

For production, the institution may configure a scheduled task or cron job.

Example weekly re-index:

```bash
0 3 * * 0 cd /var/www/html/blocks/llmassistant/rag && TARGET_COURSE_ID=5 RESET_COLLECTION=true python3 rag_ingest_moodle.py >> /var/log/llmassistant_ingest.log 2>&1
```

---

## 13. Known limitations

The assistant depends on the quality of:

- the Moodle course materials;
- the ingestion process;
- the retrieved chunks;
- the selected LLM model.

Small local models may perform well on simple PDF-based questions but may struggle with:

- tables;
- class schedules;
- row/column matching;
- abbreviations;
- questions requiring exact extraction from structured content.

For better performance, use a stronger model and/or improve the structure of Moodle content before ingestion.

---

## 14. Troubleshooting

### The Moodle chat keeps loading

Check if the RAG API is running:

```bash
curl http://127.0.0.1:8001/docs
```

Check the systemd service:

```bash
systemctl status moodle-llmassistant-rag
journalctl -u moodle-llmassistant-rag -n 100
```

### The API cannot reach Ollama

Check:

```bash
curl http://127.0.0.1:11434/api/tags
```

If Ollama is on another server, check firewall and network access.

### No answer found for a course

Check if the course was ingested:

```bash
ls -la /var/www/moodledata/chroma_db
```

Re-run:

```bash
TARGET_COURSE_ID=<courseid> RESET_COLLECTION=true python3 rag_ingest_moodle.py
```

### Permission errors

Ensure the web server user can access:

```bash
/var/www/moodledata/chroma_db
/var/www/html/blocks/llmassistant/rag
```

Example:

```bash
chown -R www-data:www-data /var/www/moodledata/chroma_db
chmod -R 775 /var/www/moodledata/chroma_db
```

---

## 15. Development notes

If JavaScript files in `amd/src` are changed, rebuild AMD assets:

```bash
npx grunt amd
```

After changing PHP files or plugin version:

```text
Site administration → Development → Purge caches
```

If `version.php` is updated, visit:

```text
/admin/index.php
```

to trigger the Moodle upgrade process.

---

## 16. Security notes

- Do not expose the RAG API publicly without authentication.
- Prefer binding Uvicorn to `127.0.0.1` when running on the same server as Moodle.
- Store database credentials securely.
- Do not commit production secrets to the plugin repository.
- Validate access control in Moodle so users only query course content they are allowed to access.

---

## 17. Files to include in the plugin ZIP

The ZIP should include the Moodle block plugin folder and the RAG scripts:

```text
llmassistant/
├── amd/
├── classes/
├── db/
├── lang/
├── pix/
├── rag/
│   ├── rag_api.py
│   ├── rag_ingest_moodle.py
│   ├── requirements.txt
│   ├── .env.example
│   └── prompts/
│       ├── system_course.txt
│       ├── system_global.txt
│       └── style.txt
├── block_llmassistant.php
├── chat.php
├── global.php
├── settings.php
├── version.php
└── README.md
```

Do not include local development files such as:

```text
moodle/
moodle-docker/
moodledata/
chroma_db/
node_modules/
vendor/
__pycache__/
*.pyc
.env
llmassistant_results/
```

---

## 18. Example `.env.example`

Create `rag/.env.example` with:

```bash
MOODLEDATA_PATH=/var/www/moodledata/filedir
CHROMA_DB_PATH=/var/www/moodledata/chroma_db

MOODLE_DB_HOST=localhost
MOODLE_DB_PORT=5432
MOODLE_DB_NAME=moodle
MOODLE_DB_USER=moodle
MOODLE_DB_PASSWORD=CHANGE_ME
MOODLE_DB_PREFIX=m_

OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_LLM_MODEL=qwen2.5:3b

LLMASSISTANT_TOP_K=30
LLMASSISTANT_MAX_CHUNKS=12
LLMASSISTANT_DEBUG=0
```

---

## 19. Important deployment note

This plugin is not a standalone Moodle-only component. It requires:

1. the Moodle block plugin to be installed;
2. the Python dependencies to be installed;
3. Moodle content to be ingested into ChromaDB;
4. the RAG API to be running continuously;
5. an LLM endpoint to be reachable.

Without these components, the chat interface may load but will not be able to generate answers.
