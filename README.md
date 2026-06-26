# Moodle LLM Assistant

`block_llmassistant` is a Moodle block plugin that provides an LLM-based assistant for Moodle courses. It uses a Retrieval-Augmented Generation (RAG) architecture to answer questions using course materials and Moodle-native content.

The plugin includes:

- A Moodle block interface for course pages.
- A dedicated course chat page.
- A global chat page for institutional/global information.
- A Python RAG API built with FastAPI/Uvicorn.
- A Moodle ingestion script that indexes course documents and Moodle-native content into ChromaDB.
- Source display for retrieved documents and Moodle-native material.
- Optional debug/result logging for evaluation, storing one JSON snapshot per question and maintaining a CSV summary.

> **Important:** the Moodle plugin does not answer questions by itself. The Python RAG API must be running, and Moodle course content must be ingested before the assistant can answer properly.

---

## Table of contents

- [1. Architecture](#1-architecture)
- [2. Requirements](#2-requirements)
  - [Moodle server](#moodle-server)
  - [Python packages](#python-packages)
- [3. Installing the Moodle plugin](#3-installing-the-moodle-plugin)
- [4. Moodle plugin configuration](#4-moodle-plugin-configuration)
- [5. Environment configuration](#5-environment-configuration)
- [6. Example `.env.example`](#6-example-envexample)
- [7. Pulling the LLM model](#7-pulling-the-llm-model)
- [8. Creating the ChromaDB directory](#8-creating-the-chromadb-directory)
- [9. Ingesting Moodle course content](#9-ingesting-moodle-course-content)
  - [Ingest a single course](#ingest-a-single-course)
  - [Rebuild a single course collection](#rebuild-a-single-course-collection)
  - [Rebuild all collections](#rebuild-all-collections)
- [10. Starting the RAG API manually](#10-starting-the-rag-api-manually)
  - [Starting manually with debug/result logging enabled](#starting-manually-with-debugresult-logging-enabled)
- [11. Running the RAG API as a system service](#11-running-the-rag-api-as-a-system-service)
- [12. Testing the RAG API](#12-testing-the-rag-api)
- [13. Using the assistant in Moodle](#13-using-the-assistant-in-moodle)
  - [Course chat](#course-chat)
  - [Dedicated course chat page](#dedicated-course-chat-page)
  - [Global chat](#global-chat)
- [14. Re-indexing strategy](#14-re-indexing-strategy)
- [15. Known limitations](#15-known-limitations)
- [16. Troubleshooting](#16-troubleshooting)
  - [The Moodle chat keeps loading](#the-moodle-chat-keeps-loading)
  - [The API cannot reach Ollama](#the-api-cannot-reach-ollama)
  - [No answer found for a course](#no-answer-found-for-a-course)
  - [Debug files are not being created](#debug-files-are-not-being-created)
  - [Database connection errors](#database-connection-errors)
  - [Permission errors](#permission-errors)
- [17. Development notes](#17-development-notes)
- [18. Security notes](#18-security-notes)
- [19. Files to include in the plugin ZIP](#19-files-to-include-in-the-plugin-zip)
- [20. Files to exclude from the plugin ZIP](#20-files-to-exclude-from-the-plugin-zip)
- [21. Creating the plugin ZIP](#21-creating-the-plugin-zip)
- [22. Validation commands before delivery](#22-validation-commands-before-delivery)
- [23. Important deployment note](#23-important-deployment-note)

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

The Moodle plugin sends user questions to the internal PHP endpoint `rag_endpoint.php`. That PHP endpoint calls the Python RAG API. The RAG API retrieves relevant course content from ChromaDB, sends the retrieved context to an LLM model, and returns the final answer and sources to Moodle.

---

## 2. Requirements

### Moodle server

- Moodle installed and working.
- Access to the Moodle web root.
- Access to the Moodle database.
- Access to `moodledata`.
- Permission to install Moodle plugins.
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
pydantic
```

Install them with:

```bash
cd /var/www/html/blocks/llmassistant/rag
pip3 install -r requirements.txt
```

If no `requirements.txt` is available, install manually:

```bash
pip3 install fastapi uvicorn chromadb requests psycopg2-binary PyMuPDF beautifulsoup4 pydantic
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

## 4. Moodle plugin configuration

After installing the plugin, configure the RAG API URL in Moodle:

```text
Site administration → Plugins → Blocks → LLM Assistant → RAG API URL
```

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

## 5. Environment configuration

A prepared environment template is provided in:

```text
rag/.env.example
```

On the production server, copy it to a secure location:

```bash
sudo mkdir -p /etc/llmassistant
sudo cp /var/www/html/blocks/llmassistant/rag/.env.example /etc/llmassistant/rag.env
sudo nano /etc/llmassistant/rag.env
sudo chmod 640 /etc/llmassistant/rag.env
```

The following values normally need to be adapted to the institution's Moodle installation:

```env
MOODLE_DB_HOST
MOODLE_DB_NAME
MOODLE_DB_USER
MOODLE_DB_PASSWORD
MOODLE_DB_PREFIX
OLLAMA_BASE_URL
OLLAMA_LLM_MODEL
LLMASSISTANT_GLOBAL_SOURCE_PATTERNS
```

`MOODLE_DB_PREFIX` must match `$CFG->prefix` in Moodle's `config.php`.

---

## 6. Example `.env.example`

The file `rag/.env.example` should contain:

```env
# =============================================================================
# Moodle LLM Assistant — Faculty deployment environment
# =============================================================================
# Copy this file to a secure location on the server, for example:
#
#   /etc/llmassistant/rag.env
#
# Then adapt the values to match the faculty Moodle installation.
#
# IMPORTANT:
# - Do not commit real passwords.
# - Do not expose this file publicly.
# - MOODLE_DB_PREFIX must match $CFG->prefix in Moodle's config.php.
# =============================================================================

MOODLEDATA_PATH=/var/www/moodledata/filedir
CHROMA_DB_PATH=/var/www/moodledata/chroma_db

MOODLE_DB_HOST=localhost
MOODLE_DB_PORT=5432
MOODLE_DB_NAME=moodle
MOODLE_DB_USER=moodle
MOODLE_DB_PASSWORD=CHANGE_ME

# Common Moodle default: mdl_
# Local moodle-docker setups may use: m_
MOODLE_DB_PREFIX=mdl_

# Comma-separated course fullname/shortname patterns used to identify
# the Moodle course that acts as the global/institutional source.
LLMASSISTANT_GLOBAL_SOURCE_PATTERNS="serviços académicos,servicos academicos,academic services"

OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_LLM_MODEL=qwen2.5:3b

LLMASSISTANT_PROMPTS_DIR=/var/www/html/blocks/llmassistant/rag/prompts

LLMASSISTANT_TOP_K=30
LLMASSISTANT_MAX_CHUNKS=12
LLMASSISTANT_MAX_CONTEXT_CHARS=9000
LLMASSISTANT_MAX_LINES_PER_CHUNK=80

LLMASSISTANT_TEMPERATURE=0.0
LLMASSISTANT_TOP_P=1.0
LLMASSISTANT_NUM_CTX=4096

LLMASSISTANT_QUERY_REWRITE=1
LLMASSISTANT_COMPRESS_CONTEXT=1

LLMASSISTANT_DISTANCE_THRESHOLD=0.93
LLMASSISTANT_CONTACT_DISTANCE_THRESHOLD=1.25

LLMASSISTANT_RERANK_ALPHA=0.55
LLMASSISTANT_RERANK_BETA=0.45

LLMASSISTANT_MATH_FORMAT=latex

# Set to 1 only for development/testing/evaluation.
# When enabled, the backend returns debug information to Moodle.
# Moodle then saves one JSON snapshot per question and updates a CSV summary.
LLMASSISTANT_DEBUG=0

# Optional ingestion controls.
# TARGET_COURSE_ID=5
# RESET_COLLECTION=true

RAG_MAX_BLOCK_CHARS=1200
RAG_BLOCK_OVERLAP=160
RAG_MIN_TEXT_CHARS=30
RAG_MIN_MOODLE_TEXT_CHARS=8
```

---

## 7. Pulling the LLM model

If using Ollama, pull the chosen model:

```bash
ollama pull qwen2.5:3b
```

For better results, especially with structured tables and schedules, the institution may use a stronger model if enough RAM/GPU resources are available, for example:

```bash
ollama pull qwen2.5:7b
ollama pull llama3.1:8b
```

Check whether Ollama is reachable:

```bash
curl http://127.0.0.1:11434/api/tags
```

---

## 8. Creating the ChromaDB directory

Create the persistent ChromaDB directory:

```bash
sudo mkdir -p /var/www/moodledata/chroma_db
sudo chown -R www-data:www-data /var/www/moodledata/chroma_db
sudo chmod -R 775 /var/www/moodledata/chroma_db
```

This directory stores the vector database and must be writable by the user running both the ingestion script and the RAG API.

---

## 9. Ingesting Moodle course content

Before using the assistant, Moodle course content must be indexed.

Load the environment file and run ingestion:

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
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
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
TARGET_COURSE_ID=5 python3 rag_ingest_moodle.py
```

### Rebuild a single course collection

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
TARGET_COURSE_ID=5 RESET_COLLECTION=true python3 rag_ingest_moodle.py
```

### Rebuild all collections

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
RESET_COLLECTION=true python3 rag_ingest_moodle.py
```

Re-run ingestion whenever course materials are added, removed, or updated.

---

## 10. Starting the RAG API manually

For testing without debug mode:

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
uvicorn rag_api:app --host 127.0.0.1 --port 8001
```

If the Moodle server needs to access the API from another machine, use:

```bash
uvicorn rag_api:app --host 0.0.0.0 --port 8001
```

Only use `0.0.0.0` if firewall and network access are properly controlled.

### Starting manually with debug/result logging enabled

For development, testing, or evaluation, the RAG API can be started with debug mode enabled:

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
LLMASSISTANT_DEBUG=1 uvicorn rag_api:app --host 127.0.0.1 --port 8001
```

In debug mode, the Python backend returns a `debug` object in each response. When Moodle receives this debug information, `rag_endpoint.php` stores an evaluation snapshot for each chat question.

Debug/result files are stored under:

```text
/var/www/moodledata/llmassistant_results
```

For each question submitted through the Moodle chat, the plugin creates:

- one JSON snapshot containing the question, request payload, backend response, final response, sources, timings, and debug fields;
- one appended row in the summary CSV file:

```text
/var/www/moodledata/llmassistant_results/all_results_summary.csv
```

The JSON files are grouped by course, for example:

```text
/var/www/moodledata/llmassistant_results/course_5_<course_shortname>/
```

Use debug mode only when detailed logs or evaluation data are needed. For normal production usage, keep:

```env
LLMASSISTANT_DEBUG=0
```

If permission errors occur when writing the result logs, ensure the Moodle web server user can write to the results folder:

```bash
sudo mkdir -p /var/www/moodledata/llmassistant_results
sudo chown -R www-data:www-data /var/www/moodledata/llmassistant_results
sudo chmod -R 775 /var/www/moodledata/llmassistant_results
```

---

## 11. Running the RAG API as a system service

Create:

```bash
/etc/systemd/system/moodle-llmassistant-rag.service
```

Example service for normal usage:

```ini
[Unit]
Description=Moodle LLM Assistant RAG API
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/html/blocks/llmassistant/rag
EnvironmentFile=/etc/llmassistant/rag.env
ExecStart=/usr/bin/python3 -m uvicorn rag_api:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

To run the service with debug/result logging enabled, either set this value in `/etc/llmassistant/rag.env`:

```env
LLMASSISTANT_DEBUG=1
```

or add this line to the `[Service]` section of the systemd unit:

```ini
Environment=LLMASSISTANT_DEBUG=1
```

When debug mode is enabled and users ask questions in the Moodle chat, JSON result snapshots and the CSV summary are written to:

```text
/var/www/moodledata/llmassistant_results
```

Enable and start the service:

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

## 12. Testing the RAG API

First, test the health endpoint:

```bash
curl http://127.0.0.1:8001/health
```

Expected response:

```json
{
  "status": "ok",
  "model": "qwen2.5:3b",
  "chroma_db_path": "/var/www/moodledata/chroma_db",
  "debug": false
}
```

If debug mode is enabled, the `debug` value should be `true`.

Then, test a question:

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

If debug mode is enabled, the response should also include a `debug` object.

If the answer says that no information was found, check:

1. The course id exists.
2. The course has been ingested.
3. The Chroma collection exists.
4. The RAG API can access the LLM endpoint.
5. The Moodle database credentials are correct.
6. `MOODLE_DB_PREFIX` matches `$CFG->prefix` in Moodle's `config.php`.

---

## 13. Using the assistant in Moodle

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

The global chat uses `courseid=0`. It resolves the institutional/global Moodle course by matching the course fullname or shortname using `LLMASSISTANT_GLOBAL_SOURCE_PATTERNS`.

If the institution uses a different Moodle course name for institutional documents, update:

```env
LLMASSISTANT_GLOBAL_SOURCE_PATTERNS="serviços académicos,servicos academicos,academic services"
```

---

## 14. Re-indexing strategy

The ingestion script should be re-run when:

- new PDFs are uploaded;
- Moodle labels/pages/books are changed;
- assignments, quizzes, URLs, folders, or resources are updated;
- dates or deadlines are updated;
- a course is imported or restored;
- the RAG logic is changed significantly.

Recommended manual re-index for one course:

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
TARGET_COURSE_ID=5 RESET_COLLECTION=true python3 rag_ingest_moodle.py
```

For production, the institution may configure a scheduled task or cron job.

Example weekly re-index:

```bash
0 3 * * 0 cd /var/www/html/blocks/llmassistant/rag && set -a && . /etc/llmassistant/rag.env && set +a && RESET_COLLECTION=true python3 rag_ingest_moodle.py >> /var/log/llmassistant_ingest.log 2>&1
```

---

## 15. Known limitations

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

## 16. Troubleshooting

### The Moodle chat keeps loading

Check if the RAG API is running:

```bash
curl http://127.0.0.1:8001/health
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

Check if course collections exist:

```bash
ls -la /var/www/moodledata/chroma_db
```

Re-run ingestion for the target course:

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
TARGET_COURSE_ID=<courseid> RESET_COLLECTION=true python3 rag_ingest_moodle.py
```

### Debug files are not being created

Debug/result files are only created when the Python backend returns debug information. Confirm that debug mode is enabled:

```bash
curl http://127.0.0.1:8001/health
```

The response should include:

```json
"debug": true
```

Then check permissions:

```bash
ls -la /var/www/moodledata/llmassistant_results
```

If needed:

```bash
sudo mkdir -p /var/www/moodledata/llmassistant_results
sudo chown -R www-data:www-data /var/www/moodledata/llmassistant_results
sudo chmod -R 775 /var/www/moodledata/llmassistant_results
```

### Database connection errors

Check these values in `/etc/llmassistant/rag.env`:

```env
MOODLE_DB_HOST
MOODLE_DB_NAME
MOODLE_DB_USER
MOODLE_DB_PASSWORD
MOODLE_DB_PREFIX
```

`MOODLE_DB_PREFIX` must match `$CFG->prefix` in Moodle's `config.php`.

### Permission errors

Ensure the web server user can access:

```bash
/var/www/moodledata/chroma_db
/var/www/html/blocks/llmassistant/rag
/var/www/moodledata/llmassistant_results
```

Example:

```bash
sudo chown -R www-data:www-data /var/www/moodledata/chroma_db
sudo chmod -R 775 /var/www/moodledata/chroma_db
sudo mkdir -p /var/www/moodledata/llmassistant_results
sudo chown -R www-data:www-data /var/www/moodledata/llmassistant_results
sudo chmod -R 775 /var/www/moodledata/llmassistant_results
```

---

## 17. Development notes

If JavaScript files in `amd/src` are changed, rebuild AMD assets:

```bash
npx grunt amd
```

After changing PHP files, language strings, or plugin settings:

```text
Site administration → Development → Purge caches
```

If `version.php` is updated, visit:

```text
/admin/index.php
```

to trigger the Moodle upgrade process.

---

## 18. Security notes

- Do not expose the RAG API publicly without authentication.
- Prefer binding Uvicorn to `127.0.0.1` when running on the same server as Moodle.
- Store database credentials securely outside the Moodle webroot, for example in `/etc/llmassistant/rag.env`.
- Do not commit production secrets to the plugin repository.
- Do not include a real `.env` file with passwords in the plugin ZIP.
- Debug mode can store user questions, assistant answers, retrieved sources, timing data, and backend debug fields in Moodledata. Enable debug mode only for development, testing, or evaluation.
- Validate access control in Moodle so users only query course content they are allowed to access.

---

## 19. Files to include in the plugin ZIP

The ZIP should include the Moodle block plugin folder and the RAG scripts:

```text
llmassistant/
├── README.md
├── ajax.php
├── block_llmassistant.php
├── chat.php
├── global.php
├── history_endpoint.php
├── rag_endpoint.php
├── settings.php
├── source_file.php
├── styles.css
├── version.php
├── amd/
│   ├── build/
│   │   ├── chat.min.js
│   │   └── chat.min.js.map
│   └── src/
│       └── chat.js
├── classes/
│   └── local/
│       ├── chat_ui.php
│       └── history_manager.php
├── db/
│   ├── access.php
│   ├── install.xml
│   └── upgrade.php
├── lang/
│   └── en/
│       └── block_llmassistant.php
├── templates/
│   └── chat_ui.mustache
└── rag/
    ├── .env.example
    ├── rag_api.py
    ├── rag_ingest_moodle.py
    ├── requirements.txt
    └── prompts/
        ├── style.txt
        ├── system_course.txt
        └── system_global.txt
```

---

## 20. Files to exclude from the plugin ZIP

Do not include local development files or generated data such as:

```text
rag/__pycache__/
rag/vectordb/
rag/*.pyc
rag/.env
moodle/
moodle-docker/
moodledata/
chroma_db/
node_modules/
vendor/
llmassistant_results/
```

Before creating the ZIP, it is recommended to run:

```bash
rm -rf rag/__pycache__
rm -rf rag/vectordb
rm -rf r
```

Then verify:

```bash
find . -name "__pycache__" -type d
find . -name "*.pyc"
find . -name "chroma.sqlite3"
find . -name "vectordb" -type d
```

---

## 21. Creating the plugin ZIP

From the Moodle `blocks` directory:

```bash
cd /path/to/moodle/blocks
zip -r llmassistant.zip llmassistant \
  -x "llmassistant/rag/__pycache__/*" \
  -x "llmassistant/rag/vectordb/*" \
  -x "llmassistant/**/*.pyc" \
  -x "llmassistant/rag/.env" \
  -x "llmassistant/llmassistant_results/*"
```

If all excluded files were removed beforehand, this is enough:

```bash
zip -r llmassistant.zip llmassistant
```

---

## 22. Validation commands before delivery

Before sending the ZIP, run:

```bash
cd /var/www/html/blocks/llmassistant
python3 -m py_compile rag/rag_api.py
python3 -m py_compile rag/rag_ingest_moodle.py
```

Also confirm the hidden `.env.example` file exists:

```bash
ls -la rag
```

---

## 23. Important deployment note

This plugin is not a standalone Moodle-only component. It requires:

1. the Moodle block plugin to be installed;
2. the Python dependencies to be installed;
3. Moodle content to be ingested into ChromaDB;
4. the RAG API to be running continuously;
5. an LLM endpoint to be reachable.

Without these components, the chat interface may load but will not be able to generate answers.
