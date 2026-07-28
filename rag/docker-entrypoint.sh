#!/bin/sh
set -eu

case "${1:-api}" in
  api)
    exec python -m uvicorn rag_api:app --host 0.0.0.0 --port "${RAG_PORT:-8001}"
    ;;
  ingest)
    shift
    exec python rag_ingest_moodle.py "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
