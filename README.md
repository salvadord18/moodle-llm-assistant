# Moodle LLM Assistant

`block_llmassistant` is a Moodle block plugin developed as the software artefact of a Master's project at NOVA Information Management School. The prototype provides an LLM-based assistant for Moodle courses and uses a Retrieval-Augmented Generation (RAG) architecture to answer questions using retrieved course-specific and institutional information.

The main evaluated configuration used course and institutional PDF collections. The prototype was subsequently extended to ingest selected Moodle-native content, including activities, links, assignments, section information and structured course elements. This later extension was tested exploratorily and was not part of the main 405-interaction evaluation.

The repository includes:

- a Moodle block interface for course pages;
- a dedicated course chat page;
- a global chat page for institutional information;
- a Python RAG API built with FastAPI and Uvicorn;
- an ingestion pipeline for course documents and selected Moodle-native content;
- persistent vector retrieval through ChromaDB;
- local LLM inference through Ollama or another compatible endpoint;
- source presentation for retrieved evidence;
- optional debug and result logging for development and evaluation;
- the question set and supporting materials used in the project evaluation.

> **Important:** the Moodle block does not operate as a standalone component. The Python RAG API must be running, an LLM endpoint must be reachable, and Moodle content must be ingested before the assistant can answer questions.

> **Project status:** this repository contains a functional research prototype. Institutional use requires additional portability, security, reliability and independent validation work.

---

## Table of contents

- [Repository structure](#repository-structure)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installing the Moodle plugin](#installing-the-moodle-plugin)
- [Moodle plugin configuration](#moodle-plugin-configuration)
- [Environment configuration](#environment-configuration)
- [Pulling the LLM model](#pulling-the-llm-model)
- [Creating the ChromaDB directory](#creating-the-chromadb-directory)
- [Ingesting Moodle course content](#ingesting-moodle-course-content)
- [Starting the RAG API manually](#starting-the-rag-api-manually)
- [Running the RAG API as a system service](#running-the-rag-api-as-a-system-service)
- [Testing the RAG API](#testing-the-rag-api)
- [Using the assistant in Moodle](#using-the-assistant-in-moodle)
- [Re-indexing strategy](#re-indexing-strategy)
- [Evaluation materials](#evaluation-materials)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Development notes](#development-notes)
- [Security notes](#security-notes)
- [Files to include in the plugin ZIP](#files-to-include-in-the-plugin-zip)
- [Files to exclude from the plugin ZIP](#files-to-exclude-from-the-plugin-zip)
- [Creating the plugin ZIP](#creating-the-plugin-zip)
- [Validation commands before delivery](#validation-commands-before-delivery)
- [Institutional deployment considerations](#institutional-deployment-considerations)
- [Academic context](#academic-context)

---

## Repository structure

The repository root corresponds to the Moodle block directory that should be installed under:

```text
moodle/blocks/llmassistant/
```

The main directories are:

```text
moodle-llm-assistant/
├── amd/          # JavaScript source and compiled Moodle AMD modules
├── classes/      # PHP classes and local plugin logic
├── db/           # Moodle permissions, database schema and upgrade definitions
├── evaluation/   # Evaluation question set and supporting project materials
├── lang/         # Moodle language strings
├── rag/          # FastAPI backend, ingestion pipeline, prompts and environment template
├── templates/    # Mustache templates for the chat interface
├── README.md
├── block_llmassistant.php
├── settings.php
├── version.php
└── ...
```

The `evaluation/` directory contains research materials associated with the project and is not required for the runtime operation of the Moodle block. The `rag/` directory contains the external Python service required for retrieval, ingestion and answer generation.

---

## Architecture

The system has three main components:

```text
Moodle block → RAG API → ChromaDB + LLM endpoint
```

### Typical same-server deployment

```text
Moodle server
├── Moodle block: /var/www/html/blocks/llmassistant
├── RAG API: http://127.0.0.1:8001/ask
├── ChromaDB: /var/www/moodledata/chroma_db
└── LLM endpoint: Ollama or another compatible service
```

### Typical distributed institutional deployment

```text
Moodle server
├── Moodle block
└── Calls the RAG API through a protected internal endpoint

RAG server
├── FastAPI RAG backend
├── ChromaDB
└── Access to the Moodle database and required Moodle content

LLM server
└── Ollama or another compatible LLM endpoint
```

The Moodle block sends user questions to the internal PHP endpoint `rag_endpoint.php`. The PHP endpoint calls the Python RAG API. The RAG API retrieves relevant course content from ChromaDB, sends the retrieved context to an LLM and returns the final answer and supporting sources to Moodle.

In a distributed deployment, the Moodle block, RAG API and LLM service must use network-accessible endpoints. Routing, firewall rules, service binding, authentication and HTTPS or equivalent institutional transport security must be validated before use.

---

## Requirements

### Moodle server

- A working Moodle installation.
- Access to the Moodle web root.
- Access to the Moodle database.
- Access to `moodledata`.
- Permission to install Moodle plugins.
- Python 3.10 or later recommended.
- `pip` and Python virtual-environment support.
- A running LLM endpoint, such as Ollama.

### Python packages

The required packages are declared in:

```text
rag/requirements.txt
```

Install them in an isolated environment:

```bash
cd /var/www/html/blocks/llmassistant/rag
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

> **Database compatibility:** the current backend was developed and tested using a direct PostgreSQL connection through `psycopg2`. Deployments using MariaDB/MySQL require adaptation of the database access layer or the introduction of a database abstraction mechanism. Changing only the database port is not sufficient.

---

## Installing the Moodle plugin

Copy the repository contents to:

```text
/var/www/html/blocks/llmassistant
```

The final paths should include:

```text
/var/www/html/blocks/llmassistant/version.php
/var/www/html/blocks/llmassistant/block_llmassistant.php
/var/www/html/blocks/llmassistant/rag/rag_api.py
/var/www/html/blocks/llmassistant/rag/rag_ingest_moodle.py
```

Then, as a Moodle administrator:

1. Go to **Site administration**.
2. Open **Notifications**, or access `/admin/index.php`.
3. Follow the Moodle plugin installation or upgrade process.
4. Purge caches if required under **Site administration → Development → Purge caches**.

---

## Moodle plugin configuration

After installing the plugin, configure the RAG API URL under:

```text
Site administration → Plugins → Blocks → LLM Assistant → RAG API URL
```

Recommended same-server value:

```text
http://127.0.0.1:8001/ask
```

Illustrative distributed-deployment value:

```text
http://rag-server.internal:8001/ask
```

Replace the illustrative hostname with an address that is resolvable and reachable from the Moodle server. Do not expose the RAG API publicly unless authentication, firewall restrictions and HTTPS are properly configured.

---

## Environment configuration

A complete environment template is available at:

```text
rag/.env.example
```

Copy the template to a secure location outside the Moodle web root:

```bash
sudo mkdir -p /etc/llmassistant
sudo cp /var/www/html/blocks/llmassistant/rag/.env.example \
  /etc/llmassistant/rag.env
sudo chmod 640 /etc/llmassistant/rag.env
```

Edit the copied file and adapt the values to the target environment:

```bash
sudo nano /etc/llmassistant/rag.env
```

At minimum, review the following variables:

```env
MOODLEDATA_PATH
CHROMA_DB_PATH
MOODLE_DB_HOST
MOODLE_DB_PORT
MOODLE_DB_NAME
MOODLE_DB_USER
MOODLE_DB_PASSWORD
MOODLE_DB_PREFIX
OLLAMA_BASE_URL
OLLAMA_LLM_MODEL
LLMASSISTANT_PROMPTS_DIR
LLMASSISTANT_GLOBAL_SOURCE_PATTERNS
```

`MOODLE_DB_PREFIX` must match `$CFG->prefix` in Moodle's `config.php`.

PostgreSQL commonly uses port `5432`, whereas MariaDB/MySQL commonly uses port `3306`. The current backend was developed and tested with PostgreSQL-specific database access and may require adaptation for other database management systems.

Use `127.0.0.1` for `OLLAMA_BASE_URL` only when Ollama and the RAG backend run on the same machine. Distributed deployments require a network-accessible endpoint and appropriate firewall, binding, authentication and transport-security configuration.

> Never commit the completed `rag.env` file or any environment file containing real credentials.

---

## Pulling the LLM model

If using Ollama, pull the selected model:

```bash
ollama pull qwen2.5:3b
```

Stronger alternatives may improve performance if suitable RAM or GPU resources are available:

```bash
ollama pull qwen2.5:7b
ollama pull llama3.1:8b
```

Check whether Ollama is reachable:

```bash
curl http://127.0.0.1:11434/api/tags
```

---

## Creating the ChromaDB directory

Create the persistent ChromaDB directory:

```bash
sudo mkdir -p /var/www/moodledata/chroma_db
sudo chown -R www-data:www-data /var/www/moodledata/chroma_db
sudo chmod -R 775 /var/www/moodledata/chroma_db
```

The directory must be writable by the operating-system user running both the ingestion script and the RAG API.

---

## Ingesting Moodle course content

Before using the assistant, authorised Moodle course content must be indexed.

Load the environment file and run ingestion:

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
.venv/bin/python rag_ingest_moodle.py
```

The pipeline creates one ChromaDB collection per Moodle course:

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
TARGET_COURSE_ID=5 .venv/bin/python rag_ingest_moodle.py
```

### Rebuild a single course collection

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
TARGET_COURSE_ID=5 RESET_COLLECTION=true .venv/bin/python rag_ingest_moodle.py
```

### Rebuild all collections

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
RESET_COLLECTION=true .venv/bin/python rag_ingest_moodle.py
```

Use `RESET_COLLECTION=true` only when a complete rebuild is intentionally required. Re-run ingestion when relevant course materials or Moodle-native elements are added, removed or changed.

---

## Starting the RAG API manually

For same-server testing without debug mode:

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
.venv/bin/python -m uvicorn rag_api:app --host 127.0.0.1 --port 8001
```

If the Moodle server must access the API from another machine:

```bash
.venv/bin/python -m uvicorn rag_api:app --host 0.0.0.0 --port 8001
```

Only bind to `0.0.0.0` when network access is restricted appropriately and the required authentication and transport-security controls are in place.

### Starting with debug and result logging enabled

For development, testing or evaluation:

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
LLMASSISTANT_DEBUG=1 .venv/bin/python -m uvicorn rag_api:app --host 127.0.0.1 --port 8001
```

When debug mode is enabled, the backend returns additional diagnostic information. `rag_endpoint.php` can then store one evaluation snapshot per question together with an appended CSV summary row.

Generated result files are stored under:

```text
/var/www/moodledata/llmassistant_results
```

Each interaction can create:

- one JSON snapshot containing the question, request payload, backend response, final response, sources, timings and debug fields;
- one appended row in `/var/www/moodledata/llmassistant_results/all_results_summary.csv`.

Use debug mode only when detailed diagnostics or evaluation data are required. For normal operation, keep:

```env
LLMASSISTANT_DEBUG=0
```

If permission errors occur:

```bash
sudo mkdir -p /var/www/moodledata/llmassistant_results
sudo chown -R www-data:www-data /var/www/moodledata/llmassistant_results
sudo chmod -R 775 /var/www/moodledata/llmassistant_results
```

---

## Running the RAG API as a system service

Create:

```text
/etc/systemd/system/moodle-llmassistant-rag.service
```

Example same-server service:

```ini
[Unit]
Description=Moodle LLM Assistant RAG API
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/html/blocks/llmassistant/rag
EnvironmentFile=/etc/llmassistant/rag.env
ExecStart=/var/www/html/blocks/llmassistant/rag/.venv/bin/python -m uvicorn rag_api:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
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

Set `LLMASSISTANT_DEBUG=1` in the protected environment file only when debug output is intentionally required.

---

## Testing the RAG API

Test the health endpoint:

```bash
curl http://127.0.0.1:8001/health
```

Illustrative response:

```json
{
  "status": "ok",
  "model": "qwen2.5:3b",
  "chroma_db_path": "/var/www/moodledata/chroma_db",
  "debug": false
}
```

Test a question:

```bash
curl -X POST http://127.0.0.1:8001/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Who are the teachers of this course?","courseid":5,"userid":1}'
```

Illustrative response:

```json
{
  "answer": "...",
  "sources": []
}
```

If no information is returned, check that:

1. the Moodle course exists;
2. the course has been ingested;
3. the corresponding ChromaDB collection exists;
4. the RAG API can access the LLM endpoint;
5. the Moodle database credentials are correct;
6. `MOODLE_DB_PREFIX` matches `$CFG->prefix` in Moodle's `config.php`.

---

## Using the assistant in Moodle

### Course chat

Add the **LLM Assistant** block to a Moodle course page. The assistant uses the current course identifier and retrieves information from:

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

The global chat uses `courseid=0` and resolves the institutional source course by matching its fullname or shortname against `LLMASSISTANT_GLOBAL_SOURCE_PATTERNS`.

---

## Re-indexing strategy

Re-run ingestion when:

- new PDFs are uploaded;
- Moodle labels, pages or books are changed;
- assignments, quizzes, URLs, folders or resources are updated;
- dates or deadlines are changed;
- a course is imported or restored;
- the ingestion or RAG logic changes significantly.

Recommended manual rebuild for one course:

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
TARGET_COURSE_ID=5 RESET_COLLECTION=true .venv/bin/python rag_ingest_moodle.py
```

For production use, re-indexing should be coordinated with institutional maintenance and content-update processes. Full collection rebuilding may temporarily affect availability and should be scheduled carefully.

Illustrative scheduled ingestion command:

```bash
0 3 * * 0 cd /var/www/html/blocks/llmassistant/rag && set -a && . /etc/llmassistant/rag.env && set +a && .venv/bin/python rag_ingest_moodle.py >> /var/log/llmassistant_ingest.log 2>&1
```

Use `RESET_COLLECTION=true` in a scheduled command only when a complete rebuild is deliberately required.

---

## Evaluation materials

The `evaluation/` directory contains materials associated with the Master's project evaluation:

```text
evaluation/
├── README.md
└── evaluation_questions.pdf
```

The main evaluation comprised 405 logged interactions across two course-scoped PDF corpora and one global regulatory corpus. The question set includes factual, conceptual, procedural and regulation-specific questions in English and Portuguese.

The later Moodle-native content tests were exploratory and were conducted after the main evaluation. They should not be interpreted as part of the 405-interaction dataset.

The evaluation materials are included for transparency and reproducibility. They are not required for the runtime operation of the Moodle block or RAG backend and should normally be excluded from deployment packages.

---

## Known limitations

The prototype should be treated as a research artefact rather than a production-ready institutional service.

Answer quality depends on:

- the quality and structure of the indexed Moodle content;
- document extraction and chunking;
- retrieval and reranking quality;
- the evidence included in the final model context;
- the capability of the selected LLM.

Small local models may perform adequately on bounded factual questions but can struggle with:

- tables and class schedules;
- row and column relationships;
- abbreviations and legends;
- conceptually similar documents;
- exact regulatory scope;
- bilingual or cross-language retrieval;
- unsupported or ambiguous questions.

The main evaluation used PDF collections. Moodle-native activities, links, sections and structured course elements were added later and assessed only through exploratory testing.

The current database integration was developed for PostgreSQL and is not directly portable to MariaDB/MySQL without adaptation. Institutional deployment also requires validation of Python and dependency compatibility, network connectivity, service endpoints, firewall rules, access control and target Moodle configuration.

---

## Troubleshooting

### The Moodle chat keeps loading

Check the API and service:

```bash
curl http://127.0.0.1:8001/health
systemctl status moodle-llmassistant-rag
journalctl -u moodle-llmassistant-rag -n 100
```

### The API cannot reach Ollama

```bash
curl http://127.0.0.1:11434/api/tags
```

If Ollama runs on another server, validate the configured endpoint, routing, firewall rules, service binding and access controls.

### No answer is found for a course

Check that the course was ingested and rebuild it if necessary:

```bash
set -a
source /etc/llmassistant/rag.env
set +a

cd /var/www/html/blocks/llmassistant/rag
TARGET_COURSE_ID=<courseid> RESET_COLLECTION=true .venv/bin/python rag_ingest_moodle.py
```

### Debug files are not being created

Confirm that `/health` reports debug mode as enabled, then check permissions:

```bash
ls -la /var/www/moodledata/llmassistant_results
```

If required:

```bash
sudo mkdir -p /var/www/moodledata/llmassistant_results
sudo chown -R www-data:www-data /var/www/moodledata/llmassistant_results
sudo chmod -R 775 /var/www/moodledata/llmassistant_results
```

### Database connection errors

Review:

```env
MOODLE_DB_HOST
MOODLE_DB_PORT
MOODLE_DB_NAME
MOODLE_DB_USER
MOODLE_DB_PASSWORD
MOODLE_DB_PREFIX
```

The prefix must match `$CFG->prefix`. MariaDB/MySQL deployments require backend adaptation; changing the port alone is not sufficient.

### Permission errors

Ensure that the service user can access the required Moodle data, ChromaDB, prompt and result paths. Apply ownership and permissions according to the institution's security policy rather than granting broader access than necessary.

---

## Development notes

If JavaScript files in `amd/src` are changed, rebuild the AMD assets from a Moodle development environment:

```bash
npx grunt amd
```

After changing PHP files, language strings or plugin settings, purge Moodle caches.

If `version.php` is updated, open `/admin/index.php` to trigger the Moodle upgrade process.

---

## Security notes

- Do not expose the RAG API publicly without authentication and transport security.
- Prefer binding Uvicorn to `127.0.0.1` for same-server deployments.
- Restrict distributed-service endpoints through appropriate firewall rules and access controls.
- Store database credentials outside the Moodle web root, for example in `/etc/llmassistant/rag.env`.
- Do not commit production secrets or a real `.env` file.
- Debug mode can store user questions, assistant answers, retrieved sources, timing data and backend debug fields in `moodledata`.
- Enable debug mode only for development, controlled testing or evaluation.
- Validate Moodle access control so that users can query only content they are authorised to access.
- Review data retention, minimisation and deletion procedures before institutional use.

---

## Files to include in the plugin ZIP

A deployment ZIP should contain the Moodle block and required RAG service files:

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
├── classes/
├── db/
├── lang/
├── templates/
└── rag/
    ├── .env.example
    ├── rag_api.py
    ├── rag_ingest_moodle.py
    ├── requirements.txt
    └── prompts/
```

The `evaluation/` directory is retained in the source repository for research transparency but is not required for runtime operation and should normally be excluded from deployment packages.

---

## Files to exclude from the plugin ZIP

Do not include local or generated material such as:

```text
.git/
evaluation/
rag/.env
rag/.venv/
rag/__pycache__/
rag/vectordb/
rag/chroma_db/
rag/*.pyc
moodledata/
chroma_db/
node_modules/
vendor/
llmassistant_results/
```

Inspect the package before delivery rather than relying only on deletion commands.

---

## Creating the plugin ZIP

From the Moodle `blocks` directory:

```bash
cd /path/to/moodle/blocks
zip -r llmassistant.zip llmassistant \
  -x "llmassistant/.git/*" \
  -x "llmassistant/evaluation/*" \
  -x "llmassistant/rag/.env" \
  -x "llmassistant/rag/.venv/*" \
  -x "llmassistant/rag/__pycache__/*" \
  -x "llmassistant/rag/vectordb/*" \
  -x "llmassistant/rag/chroma_db/*" \
  -x "llmassistant/**/*.pyc" \
  -x "llmassistant/llmassistant_results/*"
```

Inspect the archive:

```bash
unzip -l llmassistant.zip
```

Verify that it does not contain credentials, generated vector data, debug results or evaluation-only material.

---

## Validation commands before delivery

From the plugin directory:

```bash
cd /var/www/html/blocks/llmassistant
rag/.venv/bin/python -m py_compile rag/rag_api.py
rag/.venv/bin/python -m py_compile rag/rag_ingest_moodle.py
```

Confirm that the environment template and prompts exist:

```bash
ls -la rag
find rag/prompts -maxdepth 1 -type f -print
```

Search for files that should not be distributed:

```bash
find . -type f \
  \( -name ".env" -o -name "*.log" -o -name "*.pyc" -o -name "*.sqlite" -o -name "*.db" \)
```

Review the results manually before creating a release or changing the repository visibility to public.

---

## Institutional deployment considerations

A complete deployment requires:

1. the Moodle block to be installed;
2. compatible Python dependencies to be available;
3. authorised Moodle content to be ingested into ChromaDB;
4. the RAG API to run continuously;
5. an LLM endpoint to be reachable;
6. Moodle, backend and LLM endpoints to be configured correctly;
7. database access and filesystem permissions to be validated;
8. access control, authentication, firewall rules and transport security to be reviewed.

The prototype was validated functionally in a local Moodle environment. An installation in the institutional Moodle environment was attempted but not completed because of a combination of factors, including PostgreSQL/MariaDB compatibility, environment configuration, separation of services across machines and Python-version compatibility.

The incomplete institutional installation does not affect the reported local evaluation, but institutional end-to-end validation remains future work.

---

## Academic context

This software artefact was developed as part of the Master's project:

> *Leveraging the Power of LLMs in a Moodle Education Plugin: A Retrieval-Augmented Generation Approach for Course and Institutional Question Answering*

NOVA Information Management School, Universidade Nova de Lisboa.

**Author:** Salvador de Oliveira Carvalho Nunes Domingues

The repository preserves the development history relevant to the `llmassistant` component. This project repository was extracted from a broader private development repository that also contained the local Moodle environment and supporting infrastructure.
