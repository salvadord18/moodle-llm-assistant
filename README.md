# Moodle LLM Assistant Plugin

This directory is the Moodle-only component. It contains the block, Moodle pages, access control, configuration settings, and browser assets. It does not require Python, Docker, ChromaDB, or a local LLM.

## Installation

1. Copy this directory to `<moodle-root>/blocks/llmassistant`.
2. As a Moodle administrator, open **Site administration > Notifications** and complete the plugin installation.
3. Add the **LLM Assistant** block to a course when required.

## Configuration

Open **Site administration > Plugins > Blocks > LLM Assistant** and set **RAG API URL** to the API server endpoint, for example:

```text
http://rag-api.example.org:8001/ask
```

This URL is called by the Moodle server. It must not point to a Docker-only hostname unless Moodle itself runs in that Docker network. Configure the connection and request timeouts according to the expected model latency.

Set **RAG API token** to the same secret configured as `LLMASSISTANT_API_TOKEN` on the API server. Keep the token private and restrict the API firewall to the Moodle server.

## API dependency

The separate API application is documented in the [RAG API repository](https://github.com/salvadord18/moodle-llm-assistant-api). The Moodle server must be able to reach its `/health` and `/ask` endpoints. Course content must be indexed by an administrator on the API server before the assistant can answer course questions.

When creating a Moodle plugin ZIP, include the contents of this directory and exclude local development files. Do not include the separate `rag-api` directory in the plugin ZIP.