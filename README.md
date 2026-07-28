# Moodle LLM Assistant

`block_llmassistant` is a Moodle block plugin developed as the software artefact of a Master's project at NOVA Information Management School. The plugin provides an LLM-based assistant for Moodle courses and uses Retrieval-Augmented Generation (RAG) to answer questions using retrieved course-specific and institutional information.

The evaluated prototype primarily used course and institutional PDF collections. The ingestion pipeline was later extended to selected Moodle-native content, including course and section summaries, labels, pages, books, assignments, quizzes, forums, URLs, folders, and resources. The Moodle-native extension was tested exploratorily and was not part of the main 405-interaction evaluation.

The repository includes:

- a Moodle block interface for course pages;
- a dedicated course chat page;
- a global chat page for institutional information;
- configurable administration settings in Moodle;
- a Python RAG API built with FastAPI and Uvicorn;
- a dedicated Docker image for the RAG backend;
- an ingestion pipeline for PDFs and selected Moodle-native content;
- persistent vector retrieval through ChromaDB;
- local or remote LLM inference through Ollama or a compatible endpoint;
- PostgreSQL and MariaDB/MySQL database adapters;
- source presentation for retrieved evidence;
- optional debug and evaluation-result logging;
- the question set and supporting materials used in the project evaluation.

> **Important:** the Moodle block is not a standalone component. The RAG API must be running, an LLM endpoint must be reachable, and authorised Moodle content must be ingested before the assistant can answer questions.

> **Project status:** this repository contains a functional research prototype. Institutional use requires independent security, privacy, reliability, scalability, accessibility, and compatibility validation.

## Table of contents

- [Architecture](#architecture)
- [Repository structure](#repository-structure)
- [Requirements](#requirements)
- [Installing the Moodle plugin](#installing-the-moodle-plugin)
- [Moodle plugin settings](#moodle-plugin-settings)
- [Environment configuration](#environment-configuration)
- [Recommended Docker deployment](#recommended-docker-deployment)
- [Manual Python deployment](#manual-python-deployment)
- [Ingesting Moodle content](#ingesting-moodle-content)
- [Testing the RAG API](#testing-the-rag-api)
- [Using the assistant in Moodle](#using-the-assistant-in-moodle)
- [Re-indexing strategy](#re-indexing-strategy)
- [Database compatibility](#database-compatibility)
- [Evaluation materials](#evaluation-materials)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Development notes](#development-notes)
- [Security notes](#security-notes)
- [Creating a plugin ZIP](#creating-a-plugin-zip)
- [Validation before delivery](#validation-before-delivery)
- [Institutional deployment considerations](#institutional-deployment-considerations)
- [Academic context](#academic-context)

## Architecture

### Recommended containerised deployment

```text
Moodle webserver
        |
        | HTTP: http://rag-api:8001/ask
        v
RAG API service
        |-- Moodle database: PostgreSQL or MariaDB/MySQL
        |-- ChromaDB: persistent shared storage
        `-- LLM endpoint: Ollama or a compatible service
```

A typical local Docker arrangement is:

```text
Moodle/PHP container
PostgreSQL or MariaDB container
RAG API container
Ollama on the Docker host or another reachable machine
Persistent Moodledata shared where required
```

The Moodle browser interface sends requests to `rag_endpoint.php`. The PHP endpoint validates the Moodle session and course access, forwards the request to the configured Python RAG API, and returns the answer and sources to the browser.

The Python service retrieves course-aware evidence from ChromaDB, reranks and compresses the retrieved context, sends the bounded context to the configured LLM endpoint, and returns a structured response.

### Manual or same-host deployment

The RAG API can also run directly on a host using a Python virtual environment. In that arrangement, a common Moodle setting is:

```text
http://127.0.0.1:8001/ask
```

Use this address only when Moodle can reach the RAG API through the same network namespace or host. Containerised deployments normally use a Docker service name such as:

```text
http://rag-api:8001/ask
```

### Distributed institutional deployment

```text
Moodle server
    `-- Moodle block and PHP endpoint

RAG server
    |-- FastAPI/Uvicorn
    |-- ChromaDB
    `-- authorised database and Moodledata access

LLM server
    `-- Ollama or another compatible generation endpoint
```

Routing, firewall rules, DNS, authentication, HTTPS or equivalent protected transport, service binding, access control, secrets management, and data-retention requirements must be validated before institutional use.

## Repository structure

The repository root corresponds to the Moodle block directory installed as:

```text
moodle/blocks/llmassistant/
```

Main structure:

```text
llmassistant/
├── amd/                    # Moodle AMD JavaScript source and build output
├── classes/                # PHP classes and plugin logic
├── db/                     # Capabilities, schema, and upgrade definitions
├── evaluation/             # Research evaluation materials
├── lang/                   # Moodle language strings
├── rag/                    # RAG API, ingestion, prompts, and Docker image
│   ├── .dockerignore
│   ├── .env.example
│   ├── Dockerfile
│   ├── config.py
│   ├── docker-entrypoint.sh
│   ├── moodle_db.py
│   ├── rag_api.py
│   ├── rag_ingest_moodle.py
│   ├── requirements.txt
│   └── prompts/
├── templates/              # Mustache templates
├── README.md
├── block_llmassistant.php
├── settings.php
├── version.php
└── ...
```

The `evaluation/` directory is retained for research transparency and is not required at runtime.

## Requirements

### Moodle

- A supported Moodle installation.
- Administrator permission to install block plugins.
- Access to the Moodle database.
- Access to the relevant Moodledata file storage for ingestion.
- Network connectivity from Moodle to the RAG API.

### RAG backend

Recommended:

- Docker Engine or Docker Desktop with Compose support.
- Persistent storage for ChromaDB.
- Access to the Moodle database.
- Read access to authorised Moodledata content.
- Access to Ollama or another compatible generation endpoint.

Manual alternative:

- Python 3.10 or later; Python 3.11 is used by the supplied Docker image.
- `venv` and `pip`.
- Packages listed in `rag/requirements.txt`.

### LLM endpoint

The default example uses Ollama with:

```text
qwen2.5:3b
```

A stronger model may improve answer quality if adequate CPU, RAM, or GPU resources are available.

## Installing the Moodle plugin

Copy the plugin directory to:

```text
/path/to/moodle/blocks/llmassistant
```

The resulting paths should include:

```text
/path/to/moodle/blocks/llmassistant/version.php
/path/to/moodle/blocks/llmassistant/block_llmassistant.php
/path/to/moodle/blocks/llmassistant/rag/rag_api.py
/path/to/moodle/blocks/llmassistant/rag/Dockerfile
```

Then, as a Moodle administrator:

1. Open **Site administration**.
2. Open **Notifications**, or access `/admin/index.php`.
3. Complete the plugin installation or upgrade.
4. Purge Moodle caches if required.

## Moodle plugin settings

Open:

```text
Site administration
-> Plugins
-> Blocks
-> LLM Assistant
```

Available settings include:

- **RAG API URL**;
- **Connection timeout**;
- **Request timeout**;
- **Global source course ID**;
- **Global source course name patterns**;
- **Recent history messages**;
- **Enable evaluation result logging**.

Typical Docker value:

```text
http://rag-api:8001/ask
```

Typical same-host manual value:

```text
http://127.0.0.1:8001/ask
```

Illustrative distributed value:

```text
https://rag.internal.example/ask
```

Do not expose the RAG API publicly without appropriate authentication, network restrictions, and protected transport.

Recommended normal-operation values:

```text
Connection timeout: 10
Request timeout: 180
Recent history messages: 6
Enable evaluation result logging: No
```

Use an explicit Moodle course ID for the global institutional source when possible. Name patterns provide a fallback but are less robust than a stable ID.

## Environment configuration

The public template is:

```text
rag/.env.example
```

Create a real environment file outside the public repository and outside the Moodle web root. For example:

```bash
mkdir -p /opt/llmassistant/config
cp rag/.env.example /opt/llmassistant/config/rag.env
chmod 640 /opt/llmassistant/config/rag.env
```

Review at least:

```env
MOODLE_DB_TYPE=pgsql
MOODLE_DB_HOST=db
MOODLE_DB_PORT=5432
MOODLE_DB_NAME=moodle
MOODLE_DB_USER=moodle
MOODLE_DB_PASSWORD=CHANGE_ME
MOODLE_DB_PREFIX=mdl_

MOODLEDATA_PATH=/var/www/moodledata/filedir
CHROMA_DB_PATH=/var/www/moodledata/chroma_db

OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_LLM_MODEL=qwen2.5:3b
LLMASSISTANT_PROMPTS_DIR=/app/prompts
LLMASSISTANT_DEBUG=0
```

Replace `CHANGE_ME` in the real environment file. Never commit real credentials.

`MOODLE_DB_PREFIX` must match `$CFG->prefix` in Moodle's `config.php`.

Do not permanently define:

```env
RESET_COLLECTION=true
```

Set ingestion controls only on intentional one-off ingestion commands.

## Recommended Docker deployment

The repository supplies a Docker image for the Python service in `rag/Dockerfile`.

A Compose service can be defined as follows:

```yaml
services:
  rag-api:
    build:
      context: /path/to/moodle/blocks/llmassistant/rag
    restart: unless-stopped
    env_file:
      - /secure/path/rag.env
    volumes:
      - /persistent/moodledata:/var/www/moodledata
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

The exact volume and network configuration depends on the Moodle deployment. The RAG service must be able to:

- reach the Moodle database;
- read authorised files from Moodledata;
- read and write the persistent ChromaDB directory;
- reach the configured LLM endpoint.

Build the service:

```bash
docker compose build rag-api
```

Start it:

```bash
docker compose up -d rag-api
```

Check status:

```bash
docker compose ps
```

View logs:

```bash
docker compose logs --tail 100 rag-api
```

The image includes a health check against:

```text
http://127.0.0.1:8001/health
```

### Docker entrypoint modes

The default mode starts the API:

```text
api
```

The ingestion mode runs the ingestion pipeline:

```text
ingest
```

Examples:

```bash
docker compose run --rm rag-api ingest
```

```bash
docker compose run --rm \
  -e TARGET_COURSE_ID=5 \
  -e RESET_COLLECTION=false \
  rag-api ingest
```

## Manual Python deployment

For environments that do not use the supplied Docker image:

```bash
cd /path/to/moodle/blocks/llmassistant/rag
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Load the protected environment file:

```bash
set -a
source /secure/path/rag.env
set +a
```

Start the API:

```bash
python -m uvicorn rag_api:app \
  --host 127.0.0.1 \
  --port 8001
```

For a protected network deployment that must accept remote connections:

```bash
python -m uvicorn rag_api:app \
  --host 0.0.0.0 \
  --port 8001
```

Binding to `0.0.0.0` should be combined with appropriate network restrictions, authentication, and protected transport.

## Ingesting Moodle content

The ingestion pipeline creates one ChromaDB collection per Moodle course:

```text
course_docs_<courseid>
```

Example:

```text
course_docs_5
```

### Docker ingestion

Ingest one course without deleting the existing collection:

```bash
docker compose run --rm \
  -e TARGET_COURSE_ID=5 \
  -e RESET_COLLECTION=false \
  rag-api ingest
```

Intentionally rebuild one course collection:

```bash
docker compose run --rm \
  -e TARGET_COURSE_ID=5 \
  -e RESET_COLLECTION=true \
  rag-api ingest
```

All-course mode is available by omitting `TARGET_COURSE_ID`, but should be used carefully in larger deployments.

### Manual ingestion

```bash
set -a
source /secure/path/rag.env
set +a

cd /path/to/moodle/blocks/llmassistant/rag
TARGET_COURSE_ID=5 RESET_COLLECTION=false \
  .venv/bin/python rag_ingest_moodle.py
```

Re-run ingestion when relevant Moodle content is added, removed, or changed.

## Testing the RAG API

Health check:

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
  -d '{
    "question": "What is a database?",
    "courseid": 5,
    "userid": 1,
    "history": []
  }'
```

A successful response can include:

```json
{
  "answer": "...",
  "sources": ["Document.pdf (p. 10)"],
  "sources_structured": []
}
```

If no answer is found, verify:

- the Moodle course exists;
- the correct course ID is being used;
- the course was ingested;
- `course_docs_<courseid>` exists and contains records;
- Moodledata files are readable;
- the RAG API can reach the LLM endpoint;
- database credentials and prefix are correct.

## Using the assistant in Moodle

### Course block

Add the **LLM Assistant** block to a Moodle course. The assistant queries:

```text
course_docs_<current_course_id>
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

The global chat resolves an institutional source course using the configured source course ID, with name patterns as a fallback.

## Re-indexing strategy

Re-run ingestion when:

- PDFs are uploaded, removed, or replaced;
- labels, pages, or books change;
- assignments, quizzes, URLs, folders, forums, or resources change;
- section summaries or dates change;
- a course is imported or restored;
- chunking, extraction, or retrieval logic changes significantly.

Prefer rebuilding one explicit course:

```bash
docker compose run --rm \
  -e TARGET_COURSE_ID=5 \
  -e RESET_COLLECTION=true \
  rag-api ingest
```

Schedule large rebuilds carefully because they can consume CPU, storage, and database resources.

## Database compatibility

The database access layer is implemented in:

```text
rag/moodle_db.py
```

Supported configuration values:

```env
MOODLE_DB_TYPE=pgsql
```

and:

```env
MOODLE_DB_TYPE=mariadb
```

Drivers:

- PostgreSQL: `psycopg2-binary`;
- MariaDB/MySQL: `PyMySQL`.

The current local end-to-end deployment was validated with PostgreSQL. The MariaDB/MySQL adapter is implemented, but a target institutional environment should still be independently validated for SQL compatibility, character encoding, permissions, performance, and operational behaviour.

Typical ports:

```text
PostgreSQL: 5432
MariaDB/MySQL: 3306
```

Changing only the port is not sufficient; `MOODLE_DB_TYPE` must match the target database.

## Evaluation materials

The `evaluation/` directory contains materials associated with the Master's project evaluation:

```text
evaluation/
├── README.md
└── evaluation_questions.pdf
```

The main evaluation comprised 405 logged interactions across two course-scoped PDF corpora and one global regulatory corpus. The Moodle-native content extension was tested later and should not be interpreted as part of the 405-interaction dataset.

Evaluation materials are not required for runtime deployment and may be excluded from deployment packages.

## Known limitations

This project is a research prototype rather than a production-ready institutional service.

Answer quality depends on:

- indexed content quality and structure;
- PDF and HTML extraction;
- chunking;
- vector retrieval and reranking;
- context compression;
- prompt design;
- the capability of the selected LLM.

Smaller local models can struggle with:

- tables and schedules;
- row and column relationships;
- abbreviations and legends;
- closely related documents;
- precise regulatory scope;
- bilingual retrieval;
- ambiguous or unsupported questions.

Moodle-native ingestion was added after the main PDF-based evaluation and received exploratory rather than full-scale evaluation.

The Docker service improves reproducibility but does not by itself provide production authentication, auditing, high availability, monitoring, rate limiting, or protected public exposure.

## Troubleshooting

### The RAG service is unhealthy

```bash
docker compose logs --tail 200 rag-api
```

Check:

- the real environment file exists;
- `MOODLE_DB_PASSWORD` is correct;
- the database hostname is resolvable;
- `MOODLE_DB_PREFIX` matches Moodle;
- ChromaDB storage is mounted and writable;
- Moodledata is readable;
- the LLM endpoint is reachable.

### Moodle cannot reach the RAG API

From the Moodle container or host, test:

```bash
curl http://rag-api:8001/health
```

Confirm that the Moodle plugin setting uses a hostname reachable from Moodle.

### The RAG API cannot reach Ollama

```bash
curl http://host.docker.internal:11434/api/tags
```

For remote Ollama installations, verify routing, firewall rules, service binding, authentication, and transport security.

### Database connection errors

Review:

```text
MOODLE_DB_TYPE
MOODLE_DB_HOST
MOODLE_DB_PORT
MOODLE_DB_NAME
MOODLE_DB_USER
MOODLE_DB_PASSWORD
MOODLE_DB_PREFIX
```

### No information is found

Check the course ID and collection:

```bash
python - <<'PY'
from chromadb import PersistentClient
client = PersistentClient(path="/var/www/moodledata/chroma_db")
for item in client.list_collections():
    collection = client.get_collection(item.name)
    print(item.name, collection.count())
PY
```

Re-ingest the affected course if necessary.

### Permission errors

Ensure that the service user or container can:

- read the required Moodledata files;
- read and write ChromaDB;
- read prompts and configuration;
- write optional evaluation results when logging is enabled.

Apply the least privileges required by the target environment.

## Development notes

### Python validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path
for filename in [
    "rag/config.py",
    "rag/moodle_db.py",
    "rag/rag_api.py",
    "rag/rag_ingest_moodle.py",
]:
    path = Path(filename)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
    print("OK:", path)
PY
```

### Docker entrypoint validation

```bash
sh -n rag/docker-entrypoint.sh
```

### Moodle AMD JavaScript

If files under `amd/src` change, rebuild the AMD assets from a Moodle development environment:

```bash
npx --no-install grunt amd --root=blocks/llmassistant
```

After changing PHP, language strings, settings, or JavaScript, purge Moodle caches.

If `version.php` changes, open `/admin/index.php` to trigger the Moodle upgrade process.

## Security notes

- Do not expose the RAG API publicly without authentication and protected transport.
- Keep the real environment file outside Git and outside the public web root.
- Do not commit production secrets.
- Restrict database credentials to the permissions required for ingestion and lookup.
- Validate Moodle access control so users can query only authorised content.
- Treat debug and evaluation logs as potentially sensitive because they can contain questions, answers, sources, and timing information.
- Disable evaluation logging during normal operation unless explicitly required.
- Review data minimisation, retention, deletion, backup protection, and incident-response requirements before institutional deployment.
- Container separation improves deployment hygiene but is not a complete security boundary by itself.

## Creating a plugin ZIP

A deployment package should include:

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
    ├── .dockerignore
    ├── .env.example
    ├── Dockerfile
    ├── config.py
    ├── docker-entrypoint.sh
    ├── moodle_db.py
    ├── rag_api.py
    ├── rag_ingest_moodle.py
    ├── requirements.txt
    └── prompts/
```

Exclude local and generated material:

```text
.git/
evaluation/
rag/.env
rag/.venv/
rag/venv/
rag/__pycache__/
rag/*.pyc
rag/vectordb/
rag/chroma_db/
moodledata/
node_modules/
llmassistant_results/
*:Zone.Identifier
```

Create an archive from the Moodle `blocks` directory:

```bash
cd /path/to/moodle/blocks

zip -r llmassistant.zip llmassistant \
  -x "llmassistant/.git/*" \
  -x "llmassistant/evaluation/*" \
  -x "llmassistant/rag/.env" \
  -x "llmassistant/rag/.venv/*" \
  -x "llmassistant/rag/venv/*" \
  -x "llmassistant/rag/__pycache__/*" \
  -x "llmassistant/rag/vectordb/*" \
  -x "llmassistant/rag/chroma_db/*" \
  -x "llmassistant/**/*.pyc" \
  -x "llmassistant/llmassistant_results/*" \
  -x "*:Zone.Identifier"
```

Inspect the archive:

```bash
unzip -l llmassistant.zip
```

## Validation before delivery

From the plugin directory:

```bash
find . -type f -name '*:Zone.Identifier' -print
```

The command should return no output.

Check for prohibited local files:

```bash
find . -type f \
  \( -name '.env' \
     -o -name '*.log' \
     -o -name '*.pyc' \
     -o -name '*.sqlite' \
     -o -name '*.db' \)
```

Validate the public environment template:

```bash
grep '^MOODLE_DB_PASSWORD=' rag/.env.example
```

Expected:

```text
MOODLE_DB_PASSWORD=CHANGE_ME
```

Review the package manually before delivery or making a repository public.

## Institutional deployment considerations

A complete institutional deployment requires:

- installation and upgrade testing on the target Moodle version;
- database compatibility testing on the target DBMS;
- Python image and dependency validation;
- persistent and protected ChromaDB storage;
- authorised access to Moodledata;
- a continuously available RAG API;
- a reachable and approved LLM endpoint;
- network, DNS, firewall, authentication, and TLS validation;
- logging, monitoring, alerting, backup, and restore procedures;
- privacy, retention, deletion, and governance review;
- performance and concurrency testing;
- independent functional and security validation.

The prototype was evaluated locally. Earlier institutional installation attempts were not completed because of environment differences, including database, service separation, configuration, and dependency compatibility. The new database adapter and Docker service improve portability, but they do not replace target-environment validation.

## Academic context

This software artefact was developed as part of the Master's project:

_Leveraging the Power of LLMs in a Moodle Education Plugin: A Retrieval-Augmented Generation Approach for Course and Institutional Question Answering_

NOVA Information Management School, Universidade Nova de Lisboa.

**Author:** Salvador de Oliveira Carvalho Nunes Domingues

The public plugin repository is extracted from a broader private development repository that also contains the local Moodle environment and supporting infrastructure.
